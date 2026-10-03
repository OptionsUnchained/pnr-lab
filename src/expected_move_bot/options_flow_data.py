from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tastytrade import DXLinkStreamer, Session
from tastytrade.dxfeed import Candle, Summary, Trade
from tastytrade.instruments import Equity, NestedOptionChain

from expected_move_bot.gex_data import (
    ContractSpec,
    build_contract_specs,
    collect_events,
    subscribe_in_batches,
    trade_values,
)
from expected_move_bot.market_data import finite_float, normalize_symbol
from expected_move_bot.movers import PACIFIC
from expected_move_bot.options_flow import (
    ContractFlow,
    OptionsFlowSnapshot,
    aggregate_top_strikes,
    scale_sides,
    top_strikes,
)

UTC = ZoneInfo("UTC")
TOP_STRIKES = 10


class TastytradeOptionsFlowData:
    def __init__(self, provider_secret: str, refresh_token: str) -> None:
        self.provider_secret = provider_secret
        self.refresh_token = refresh_token

    async def snapshot(
        self, raw_symbol: str, raw_expiration: str
    ) -> OptionsFlowSnapshot:
        symbol = normalize_symbol(raw_symbol)
        try:
            requested_expiration = date.fromisoformat(raw_expiration.strip())
        except ValueError as exc:
            raise ValueError("Select a monthly expiration in YYYY-MM-DD format") from exc

        as_of = datetime.now(PACIFIC)
        async with Session(self.provider_secret, self.refresh_token) as session:
            equity = await Equity.get(session, symbol)
            chains, underlying_trade = await asyncio.gather(
                NestedOptionChain.get(session, symbol),
                self._trade_snapshot(session, equity.streamer_symbol),
            )
            price, change, change_percent = trade_values(underlying_trade)
            if not any(
                expiration.expiration_date == requested_expiration
                and expiration.expiration_type.lower() == "regular"
                for chain in chains
                for expiration in chain.expirations
            ):
                raise ValueError(
                    f"{requested_expiration:%b %d, %Y} is not an available monthly "
                    f"expiration for {symbol}"
                )
            specs = build_contract_specs(
                chains,
                expiration_dates={requested_expiration},
                spot_price=price,
                strike_limit=None,
            )
            flows, session_date = await collect_contract_flows(session, specs)

        rows = aggregate_top_strikes(flows, TOP_STRIKES)
        if not rows:
            raise LookupError(
                f"No current-session option volume returned for {symbol} "
                f"{requested_expiration:%b %d}"
            )
        return OptionsFlowSnapshot(
            symbol=symbol,
            description=equity.short_description or equity.description,
            price=price,
            change=change,
            change_percent=change_percent,
            as_of=as_of,
            session_date=session_date,
            expiration_date=requested_expiration,
            rows=rows,
        )

    @staticmethod
    async def _trade_snapshot(session: Session, streamer_symbol: str) -> Trade:
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Trade, [streamer_symbol])
            events = await collect_events(streamer, Trade, {streamer_symbol}, timeout=12)
        trade = events.get(streamer_symbol)
        if trade is None:
            raise LookupError("Timed out waiting for the underlying price")
        return trade


async def collect_contract_flows(
    session: Session, specs: list[ContractSpec]
) -> tuple[list[ContractFlow], date]:
    specs_by_symbol = {spec.streamer_symbol: spec for spec in specs}
    symbols = set(specs_by_symbol)
    async with DXLinkStreamer(session) as streamer:
        await subscribe_in_batches(streamer, Trade, symbols)
        trades = await collect_events(streamer, Trade, symbols, timeout=25)
        await streamer.unsubscribe_all(Trade)
        await subscribe_in_batches(streamer, Summary, symbols)
        summaries = await collect_events(streamer, Summary, symbols, timeout=25)
        await streamer.unsubscribe_all(Summary)

        dated_trades = [trade for trade in trades.values() if trade.day_volume is not None]
        if not dated_trades:
            raise LookupError("Tastytrade returned no current-session option volume")
        latest_day_id = max(trade.day_id for trade in dated_trades)
        session_date = date(1970, 1, 1) + timedelta(days=latest_day_id)

        preliminary_by_symbol: dict[str, ContractFlow] = {}
        for symbol, trade in trades.items():
            if trade.day_id != latest_day_id:
                continue
            volume = int(finite_float(trade.day_volume) or 0)
            if volume <= 0:
                continue
            spec = specs_by_symbol[symbol]
            summary = summaries.get(symbol)
            preliminary_by_symbol[symbol] = ContractFlow(
                strike=spec.strike,
                is_call=spec.is_call,
                volume=volume,
                open_interest=max(0, summary.open_interest if summary else 0),
                turnover=max(0.0, finite_float(trade.day_turnover) or 0.0),
                multiplier=spec.multiplier,
            )
        selected_strikes = set(top_strikes(list(preliminary_by_symbol.values()), TOP_STRIKES))
        selected_symbols = {
            symbol
            for symbol, spec in specs_by_symbol.items()
            if spec.strike in selected_strikes
        }
        candle_sides = await collect_candle_sides(
            streamer,
            selected_symbols,
            session_date,
        )

    output = []
    for symbol in selected_symbols:
        spec = specs_by_symbol[symbol]
        base = preliminary_by_symbol.get(symbol)
        if base is None:
            summary = summaries.get(symbol)
            base = ContractFlow(
                strike=spec.strike,
                is_call=spec.is_call,
                volume=0,
                open_interest=max(0, summary.open_interest if summary else 0),
                turnover=0.0,
                multiplier=spec.multiplier,
            )
        buy, sell = scale_sides(base.volume, *candle_sides.get(symbol, (0.0, 0.0)))
        output.append(
            ContractFlow(
                strike=base.strike,
                is_call=base.is_call,
                volume=base.volume,
                open_interest=base.open_interest,
                turnover=base.turnover,
                buy_volume=buy,
                sell_volume=sell,
                multiplier=spec.multiplier,
            )
        )
    return output, session_date


async def collect_candle_sides(
    streamer: DXLinkStreamer,
    symbols: set[str],
    session_date: date,
) -> dict[str, tuple[float, float]]:
    if not symbols:
        return {}
    market_open = datetime.combine(session_date, time(6, 30), PACIFIC).astimezone(UTC)
    await streamer.subscribe_candle(
        symbols,
        "1m",
        start_time=market_open,
        extended_trading_hours=False,
        refresh_interval=1.0,
    )
    candles: dict[tuple[str, int], Candle] = {}

    async def receive() -> None:
        async for candle in streamer.listen(Candle):
            symbol = candle.event_symbol.split("{", 1)[0]
            if symbol in symbols and not candle.remove:
                candles[(symbol, candle.time)] = candle

    with suppress(TimeoutError):
        await asyncio.wait_for(receive(), timeout=12)
    sides: dict[str, list[float]] = {}
    for (symbol, _), candle in candles.items():
        values = sides.setdefault(symbol, [0.0, 0.0])
        values[0] += max(0.0, finite_float(candle.ask_volume) or 0.0)
        values[1] += max(0.0, finite_float(candle.bid_volume) or 0.0)
    return {symbol: (values[0], values[1]) for symbol, values in sides.items()}
