from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import islice

from tastytrade import DXLinkStreamer, Session
from tastytrade.dxfeed import Candle, Quote, Summary, Trade
from tastytrade.instruments import Equity, NestedOptionChain
from tastytrade.metrics import get_earnings, get_market_metrics

from expected_move_bot.calculations import (
    ExpectedMoveRow,
    build_expected_move_rows,
    choose_regular_expirations,
)
from expected_move_bot.earnings import (
    EARNINGS_PROVIDER_SYMBOLS,
    TRACKED_EARNINGS_SYMBOLS,
    EarningsEvent,
    EarningsSnapshot,
    estimate_earnings_date,
    sort_earnings_events,
)
from expected_move_bot.movers import (
    MARKET_CAP_MINIMUM,
    MOVERS_LIMIT,
    PACIFIC,
    MarketMover,
    MarketMoversSnapshot,
    MoversMode,
    rank_market_movers,
)


@dataclass(frozen=True)
class ExpectedMoveSnapshot:
    symbol: str
    price: float
    iv: float
    iv_rank: float | None
    rows: list[ExpectedMoveRow]


class TastytradeMarketData:
    def __init__(self, provider_secret: str, refresh_token: str) -> None:
        self.provider_secret = provider_secret
        self.refresh_token = refresh_token
        self._large_cap_universe: dict[str, tuple[str, float]] = {}
        self._large_cap_loaded_at: datetime | None = None

    async def earnings_snapshot(self) -> EarningsSnapshot:
        as_of = datetime.now(PACIFIC).date()
        provider_symbols = [
            EARNINGS_PROVIDER_SYMBOLS.get(symbol, symbol)
            for symbol in TRACKED_EARNINGS_SYMBOLS
        ]
        display_symbols = {
            provider_symbol: display_symbol
            for display_symbol, provider_symbol in zip(
                TRACKED_EARNINGS_SYMBOLS,
                provider_symbols,
                strict=True,
            )
        }
        async with Session(self.provider_secret, self.refresh_token) as session:
            metrics = await get_market_metrics(session, provider_symbols)
            metrics_by_symbol = {
                display_symbols.get(metric.symbol, metric.symbol): metric for metric in metrics
            }
            events_by_symbol: dict[str, EarningsEvent] = {}
            missing_symbols = []
            for symbol in TRACKED_EARNINGS_SYMBOLS:
                metric = metrics_by_symbol.get(symbol)
                report = metric.earnings if metric is not None else None
                report_date = report.expected_report_date if report is not None else None
                if report_date is None or report_date < as_of:
                    missing_symbols.append(symbol)
                    continue
                events_by_symbol[symbol] = EarningsEvent(
                    symbol=symbol,
                    report_date=report_date,
                    market_cap=(
                        float(metric.market_cap)
                        if metric is not None and metric.market_cap is not None
                        else None
                    ),
                    confirmed=report.estimated is False,
                )

            history_limit = asyncio.Semaphore(6)

            async def get_history(symbol: str):
                async with history_limit:
                    return await get_earnings(
                        session,
                        EARNINGS_PROVIDER_SYMBOLS.get(symbol, symbol),
                        as_of - timedelta(days=800),
                    )

            history_results = await asyncio.gather(
                *(get_history(symbol) for symbol in missing_symbols),
                return_exceptions=True,
            )

        for symbol, result in zip(missing_symbols, history_results, strict=True):
            estimated_date = None
            if not isinstance(result, BaseException):
                estimated_date = estimate_earnings_date(
                    [item.occurred_date for item in result],
                    as_of,
                )
            events_by_symbol[symbol] = EarningsEvent(
                symbol=symbol,
                report_date=estimated_date,
                market_cap=(
                    float(metrics_by_symbol[symbol].market_cap)
                    if symbol in metrics_by_symbol
                    and metrics_by_symbol[symbol].market_cap is not None
                    else None
                ),
                calculated=estimated_date is not None,
            )

        events = [events_by_symbol[symbol] for symbol in TRACKED_EARNINGS_SYMBOLS]
        return EarningsSnapshot(as_of=as_of, events=sort_earnings_events(events))

    async def market_movers_snapshot(
        self,
        market_cap_minimum: float = MARKET_CAP_MINIMUM,
        limit: int = MOVERS_LIMIT,
        mode: MoversMode = MoversMode.REGULAR,
    ) -> MarketMoversSnapshot:
        as_of = datetime.now(PACIFIC)
        async with Session(self.provider_secret, self.refresh_token) as session:
            universe = await self._get_large_cap_universe(session, market_cap_minimum)
            if mode == MoversMode.REGULAR:
                trades = await self._trade_snapshots(session, list(universe))
                movers = self._regular_session_movers(as_of, universe, trades)
            else:
                prices, summaries = await self._extended_trade_summary_snapshots(
                    session,
                    list(universe),
                    as_of,
                    mode,
                )
                movers = self._extended_session_movers(
                    universe,
                    prices,
                    summaries,
                    mode,
                )

        if not movers:
            raise LookupError(f"No usable {mode.value} large-cap prices were returned")
        gainers, losers = rank_market_movers(movers, limit)
        return MarketMoversSnapshot(
            as_of=as_of,
            gainers=gainers,
            losers=losers,
            eligible_count=len(universe),
            quoted_count=len(movers),
            mode=mode,
        )


    @staticmethod
    def _regular_session_movers(
        as_of: datetime,
        universe: dict[str, tuple[str, float]],
        trades: dict[str, Trade],
    ) -> list[MarketMover]:
        today_id = (as_of.date() - date(1970, 1, 1)).days
        movers: list[MarketMover] = []
        for streamer_symbol, trade in trades.items():
            if trade.day_id != today_id:
                continue
            price = finite_float(trade.price)
            change = finite_float(trade.change)
            if price is None or change is None:
                continue
            previous_close = price - change
            if price <= 0 or previous_close <= 0:
                continue
            display_symbol, market_cap = universe[streamer_symbol]
            movers.append(
                MarketMover(
                    symbol=display_symbol,
                    price=price,
                    change=change,
                    change_percent=change / previous_close,
                    market_cap=market_cap,
                )
            )
        return movers

    @staticmethod
    def _extended_session_movers(
        universe: dict[str, tuple[str, float]],
        prices: dict[str, float],
        summaries: dict[str, Summary],
        mode: MoversMode,
    ) -> list[MarketMover]:
        movers: list[MarketMover] = []
        for streamer_symbol, price in prices.items():
            summary = summaries.get(streamer_symbol)
            if summary is None:
                continue
            if mode == MoversMode.PREMARKET:
                reference = finite_float(summary.prev_day_close_price)
            elif mode == MoversMode.AFTER_MARKET:
                reference = finite_float(summary.day_close_price)
            else:
                raise ValueError(f"Unsupported extended-hours mode: {mode}")
            if price <= 0 or reference is None or reference <= 0:
                continue
            change = price - reference
            display_symbol, market_cap = universe[streamer_symbol]
            movers.append(
                MarketMover(
                    symbol=display_symbol,
                    price=price,
                    change=change,
                    change_percent=change / reference,
                    market_cap=market_cap,
                )
            )
        return movers

    async def _get_large_cap_universe(
        self, session: Session, market_cap_minimum: float
    ) -> dict[str, tuple[str, float]]:
        now = datetime.now(PACIFIC)
        if (
            self._large_cap_universe
            and self._large_cap_loaded_at is not None
            and now - self._large_cap_loaded_at < timedelta(hours=20)
        ):
            return self._large_cap_universe

        equities = await Equity.get_active_equities(session, per_page=1000, page_offset=None)
        candidates = [
            equity
            for equity in equities
            if equity.active
            and not equity.is_index
            and not equity.is_etf
            and not equity.is_illiquid
            and not equity.is_closing_only
        ]

        market_caps: dict[str, float] = {}
        for batch_group in batched(candidates, 200):
            # Read the raw endpoint for the movers universe. The SDK validates
            # every nested option-expiration record even though this scan only
            # needs market cap; one incomplete historical record can otherwise
            # reject an entire batch of 200 symbols.
            payload = await session._get(
                "/market-metrics",
                params={"symbols": ",".join(equity.symbol for equity in batch_group)},
            )
            market_caps.update(
                extract_market_caps(payload.get("items", []), market_cap_minimum)
            )
        universe = {
            equity.streamer_symbol: (equity.symbol, market_caps[equity.symbol])
            for equity in candidates
            if equity.symbol in market_caps and equity.streamer_symbol
        }
        if len(universe) < 30:
            raise LookupError("Tastytrade returned too few companies above the market-cap filter")
        self._large_cap_universe = universe
        self._large_cap_loaded_at = now
        return universe

    @staticmethod
    async def _trade_snapshots(session: Session, symbols: list[str]) -> dict[str, Trade]:
        targets = set(symbols)
        trades: dict[str, Trade] = {}
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Trade, targets)

            async def collect_trades() -> None:
                async for trade in streamer.listen(Trade):
                    if trade.event_symbol in targets:
                        trades[trade.event_symbol] = trade
                    if trades.keys() >= targets:
                        return

            with suppress(TimeoutError):
                await asyncio.wait_for(collect_trades(), timeout=20)
        if len(trades) < 30:
            raise LookupError("Too few live equity trades were returned by Tastytrade")
        return trades

    @staticmethod
    async def _extended_trade_summary_snapshots(
        session: Session,
        symbols: list[str],
        as_of: datetime,
        mode: MoversMode,
    ) -> tuple[dict[str, float], dict[str, Summary]]:
        targets = set(symbols)
        session_start, session_end = extended_session_bounds(as_of, mode)
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Summary, targets)
            summaries = await collect_stream_events(streamer, Summary, targets, timeout=20)
            await streamer.unsubscribe_all(Summary)

            # A Candle subscription for the full $20B+ universe exceeds
            # DXLink's subscription-size limit. Trade snapshots support this
            # universe and expose both the extended-hours flag and exact trade
            # timestamp, which also matches the intended "last trade" report.
            await streamer.subscribe(Trade, targets)
            trades = await collect_stream_events(
                streamer, Trade, targets, timeout=20
            )
            prices = extended_trade_prices(trades, session_start, session_end)
        if len(prices) < 30 or len(summaries) < 30:
            raise LookupError("Too few extended-hours trades were returned by Tastytrade")
        return prices, summaries

    async def expected_move_snapshot(self, raw_symbol: str) -> ExpectedMoveSnapshot:
        symbol = normalize_symbol(raw_symbol)
        async with Session(self.provider_secret, self.refresh_token) as session:
            metrics_result, chains = await asyncio.gather(
                get_market_metrics(session, [symbol]),
                NestedOptionChain.get(session, symbol),
            )
            if not metrics_result:
                raise LookupError(f"No Tastytrade market metrics found for {symbol}")
            if not chains:
                raise LookupError(f"No listed option chain found for {symbol}")

            metric = metrics_result[0]
            # Tastytrade's IV index is already a decimal (for example, 0.352),
            # while the separate 30-day field is returned in percentage points
            # (for example, 35.2). Prefer IVx to match the platform display.
            if metric.implied_volatility_index is not None:
                iv = normalize_iv(metric.implied_volatility_index, percentage_points=False)
            elif metric.implied_volatility_30_day is not None:
                iv = normalize_iv(metric.implied_volatility_30_day, percentage_points=True)
            else:
                raise LookupError(f"No IV data found for {symbol}")
            if not math.isfinite(iv) or iv < 0:
                raise LookupError(f"Invalid IV data returned for {symbol}")

            price = await self._quote_midpoint(session, symbol)
            all_expirations = [expiration for chain in chains for expiration in chain.expirations]
            selected = choose_regular_expirations(all_expirations)

            expected_move_legs = []
            for expiration in selected:
                strikes = sorted(
                    expiration.strikes,
                    key=lambda item: float(item.strike_price),
                )
                if len(strikes) < 5:
                    raise LookupError(
                        f"Not enough strikes found for {symbol} {expiration.expiration_date}"
                    )
                atm_index = min(
                    range(len(strikes)),
                    key=lambda index: abs(float(strikes[index].strike_price) - price),
                )
                if atm_index < 2 or atm_index + 2 >= len(strikes):
                    raise LookupError(
                        f"Not enough surrounding strikes for {symbol} "
                        f"{expiration.expiration_date}"
                    )
                atm = strikes[atm_index]
                first_lower = strikes[atm_index - 1]
                second_lower = strikes[atm_index - 2]
                first_higher = strikes[atm_index + 1]
                second_higher = strikes[atm_index + 2]
                expected_move_legs.append(
                    (
                        expiration,
                        atm.call_streamer_symbol,
                        atm.put_streamer_symbol,
                        first_higher.call_streamer_symbol,
                        first_lower.put_streamer_symbol,
                        second_higher.call_streamer_symbol,
                        second_lower.put_streamer_symbol,
                    )
                )

            option_symbols = [
                option_symbol
                for leg_set in expected_move_legs
                for option_symbol in leg_set[1:]
            ]
            option_midpoints = await self._quote_midpoints(session, option_symbols)
            rows = build_expected_move_rows(
                price,
                (
                    (
                        expiration,
                        *(option_midpoints[option_symbol] for option_symbol in option_symbols),
                    )
                    for expiration, *option_symbols in expected_move_legs
                ),
            )

            rank_value = metric.implied_volatility_index_rank
            rank = float(rank_value) if rank_value is not None else None
            return ExpectedMoveSnapshot(
                symbol=symbol,
                price=price,
                iv=iv,
                iv_rank=rank,
                rows=rows,
            )

    @staticmethod
    async def _quote_midpoint(session: Session, symbol: str) -> float:
        return (await TastytradeMarketData._quote_midpoints(session, [symbol]))[symbol]

    @staticmethod
    async def _quote_midpoints(session: Session, symbols: list[str]) -> dict[str, float]:
        targets = set(symbols)
        quotes: dict[str, Quote] = {}

        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Quote, targets)

            async def collect_quotes() -> None:
                async for quote in streamer.listen(Quote):
                    if quote.event_symbol in targets:
                        quotes[quote.event_symbol] = quote
                    if quotes.keys() >= targets:
                        return

            try:
                await asyncio.wait_for(collect_quotes(), timeout=15)
            except TimeoutError as exc:
                missing = ", ".join(sorted(targets - quotes.keys()))
                raise LookupError(f"Timed out waiting for option quotes: {missing}") from exc

        midpoints: dict[str, float] = {}
        for symbol in targets:
            quote = quotes[symbol]
            midpoint = quote_midpoint(quote)
            if midpoint is None:
                raise LookupError(f"No usable live bid/ask quote found for {symbol}")
            midpoints[symbol] = midpoint
        return midpoints


async def earnings_event_for_symbol(
    session: Session,
    symbol: str,
    as_of: date,
) -> EarningsEvent:
    """Resolve one symbol using the same hierarchy as the earnings command."""
    provider_symbol = EARNINGS_PROVIDER_SYMBOLS.get(symbol, symbol)
    metrics = await get_market_metrics(session, [provider_symbol])
    metric = metrics[0] if metrics else None
    report = metric.earnings if metric is not None else None
    report_date = report.expected_report_date if report is not None else None
    market_cap = (
        float(metric.market_cap)
        if metric is not None and metric.market_cap is not None
        else None
    )
    if report_date is not None and report_date >= as_of:
        return EarningsEvent(
            symbol=symbol,
            report_date=report_date,
            market_cap=market_cap,
            confirmed=report.estimated is False,
        )

    history = await get_earnings(
        session,
        provider_symbol,
        as_of - timedelta(days=800),
    )
    estimated_date = estimate_earnings_date(
        [item.occurred_date for item in history],
        as_of,
    )
    return EarningsEvent(
        symbol=symbol,
        report_date=estimated_date,
        market_cap=market_cap,
        calculated=estimated_date is not None,
    )


def finite_float(value: Decimal | float | str | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def quote_midpoint(quote: Quote) -> float | None:
    bid = finite_float(quote.bid_price)
    ask = finite_float(quote.ask_price)
    if bid is None or ask is None or bid < 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


async def collect_stream_events(streamer, event_type, targets: set[str], *, timeout: float):
    events = {}

    async def receive() -> None:
        async for event in streamer.listen(event_type):
            if event.event_symbol in targets:
                events[event.event_symbol] = event
            if events.keys() >= targets:
                return

    with suppress(TimeoutError):
        await asyncio.wait_for(receive(), timeout=timeout)
    return events


def extended_session_bounds(
    as_of: datetime, mode: MoversMode
) -> tuple[datetime, datetime]:
    local = as_of.astimezone(PACIFIC)
    if mode == MoversMode.PREMARKET:
        start = datetime.combine(local.date(), time(1, 0), tzinfo=PACIFIC)
        market_open = datetime.combine(local.date(), time(6, 30), tzinfo=PACIFIC)
        end = min(local, market_open)
    elif mode == MoversMode.AFTER_MARKET:
        start = datetime.combine(local.date(), time(13, 0), tzinfo=PACIFIC)
        end = local
    else:
        raise ValueError(f"No extended-hours window for mode: {mode}")
    if end <= start:
        raise LookupError(f"The {mode.value} session has not started yet")
    return start, end


async def collect_latest_candle_prices(
    streamer,
    targets: set[str],
    session_start: datetime,
    session_end: datetime,
    *,
    timeout: float,
) -> dict[str, float]:
    prices: dict[str, float] = {}
    latest_times: dict[str, int] = {}

    async def receive() -> None:
        async for candle in streamer.listen(Candle):
            symbol = candle.event_symbol.split("{", 1)[0]
            if symbol not in targets or candle.count <= 0:
                continue
            candle_time = datetime.fromtimestamp(candle.time / 1000, tz=PACIFIC)
            if not session_start <= candle_time <= session_end:
                continue
            price = finite_float(candle.close)
            if price is None or price <= 0:
                continue
            if candle.time >= latest_times.get(symbol, -1):
                latest_times[symbol] = candle.time
                prices[symbol] = price

    with suppress(TimeoutError):
        await asyncio.wait_for(receive(), timeout=timeout)
    return prices


def extended_trade_prices(
    trades: dict[str, Trade],
    session_start: datetime,
    session_end: datetime,
) -> dict[str, float]:
    """Return last trades that actually occurred in the extended session."""
    prices: dict[str, float] = {}
    for symbol, trade in trades.items():
        if not trade.extended_trading_hours:
            continue
        trade_time = datetime.fromtimestamp(trade.time / 1000, tz=PACIFIC)
        if not session_start <= trade_time <= session_end:
            continue
        price = finite_float(trade.price)
        if price is not None and price > 0:
            prices[symbol] = price
    return prices


def extract_market_caps(items: list[dict], minimum: float) -> dict[str, float]:
    """Extract market caps without validating unrelated nested metrics fields."""
    result: dict[str, float] = {}
    for item in items:
        symbol = item.get("symbol")
        market_cap = finite_float(item.get("market-cap"))
        if isinstance(symbol, str) and market_cap is not None and market_cap >= minimum:
            result[symbol] = market_cap
    return result


def normalize_iv(value: Decimal | float, *, percentage_points: bool) -> float:
    """Normalize an annualized IV value to decimal form."""
    result = float(value)
    return result / 100 if percentage_points else result


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper().replace("$", "")
    if not symbol or len(symbol) > 12:
        raise ValueError("Enter a valid ticker symbol")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-")
    if any(character not in allowed for character in symbol):
        raise ValueError("Ticker contains unsupported characters")
    return symbol


def batched(items: list[Equity], size: int) -> Iterator[list[Equity]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch
