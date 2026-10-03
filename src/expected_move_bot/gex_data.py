from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import islice

from tastytrade import DXLinkStreamer, Session
from tastytrade.dxfeed import Greeks, Summary, Trade
from tastytrade.instruments import Equity, NestedOptionChain, NestedOptionChainExpiration

from expected_move_bot.earnings import EarningsEvent
from expected_move_bot.gex import (
    GexExpirySnapshot,
    GexStrikeSnapshot,
    OptionGexInput,
    aggregate_gex_by_expiry,
    aggregate_gex_by_strike,
    select_material_strikes,
)
from expected_move_bot.market_data import (
    earnings_event_for_symbol,
    finite_float,
    normalize_symbol,
)
from expected_move_bot.movers import PACIFIC

MAX_OVERVIEW_EXPIRATIONS = 36
NEAR_TERM_EXPIRATIONS = 16
OVERVIEW_STRIKES_PER_EXPIRATION = 120
STREAM_SUBSCRIPTION_BATCH = 500
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractSpec:
    streamer_symbol: str
    expiration_date: date
    strike: float
    is_call: bool
    multiplier: int


class TastytradeGexData:
    def __init__(self, provider_secret: str, refresh_token: str) -> None:
        self.provider_secret = provider_secret
        self.refresh_token = refresh_token
        self._expiration_cache: dict[str, tuple[datetime, list[date]]] = {}

    async def regular_expirations(self, raw_symbol: str) -> list[date]:
        symbol = normalize_symbol(raw_symbol)
        now = datetime.now(PACIFIC)
        cached = self._expiration_cache.get(symbol)
        if cached and now - cached[0] < timedelta(minutes=15):
            return cached[1]

        async with Session(self.provider_secret, self.refresh_token) as session:
            chains = await NestedOptionChain.get(session, symbol)
        expirations = sorted(
            {
                expiration.expiration_date
                for chain in chains
                for expiration in chain.expirations
                if expiration.expiration_type.lower() == "regular"
                and expiration.days_to_expiration >= 0
            }
        )
        self._expiration_cache[symbol] = (now, expirations)
        return expirations

    async def expiry_snapshot(self, raw_symbol: str) -> GexExpirySnapshot:
        symbol = normalize_symbol(raw_symbol)
        as_of = datetime.now(PACIFIC)
        async with Session(self.provider_secret, self.refresh_token) as session:
            equity = await Equity.get(session, symbol)
            chains, trade = await asyncio.gather(
                NestedOptionChain.get(session, symbol),
                self._trade_snapshot(session, equity.streamer_symbol),
            )
            price, change, change_percent = trade_values(trade)
            expirations = choose_overview_expirations(chains)
            specs = build_contract_specs(
                chains,
                expiration_dates={item.expiration_date for item in expirations},
                spot_price=price,
                strike_limit=OVERVIEW_STRIKES_PER_EXPIRATION,
            )
            contracts, received, requested = await collect_gex_inputs(session, specs)
            earnings = await safe_earnings_event(session, symbol, as_of.date())

        rows = aggregate_gex_by_expiry(contracts, price)
        if not rows:
            raise LookupError(f"No usable GEX data returned for {symbol}")
        return GexExpirySnapshot(
            symbol=symbol,
            description=equity.short_description or equity.description,
            price=price,
            change=change,
            change_percent=change_percent,
            as_of=as_of,
            rows=rows,
            contracts_received=received,
            contracts_requested=requested,
            earnings_date=earnings.report_date,
            earnings_confirmed=earnings.confirmed,
            earnings_calculated=earnings.calculated,
        )

    async def strike_snapshot(
        self, raw_symbol: str, raw_expiration: str
    ) -> GexStrikeSnapshot:
        symbol = normalize_symbol(raw_symbol)
        as_of = datetime.now(PACIFIC)
        try:
            requested_expiration = date.fromisoformat(raw_expiration.strip())
        except ValueError as exc:
            raise ValueError("Select a monthly expiration in YYYY-MM-DD format") from exc

        async with Session(self.provider_secret, self.refresh_token) as session:
            equity = await Equity.get(session, symbol)
            chains, trade = await asyncio.gather(
                NestedOptionChain.get(session, symbol),
                self._trade_snapshot(session, equity.streamer_symbol),
            )
            price, change, change_percent = trade_values(trade)
            matching = [
                expiration
                for chain in chains
                for expiration in chain.expirations
                if expiration.expiration_date == requested_expiration
                and expiration.expiration_type.lower() == "regular"
            ]
            if not matching:
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
            contracts, received, requested = await collect_gex_inputs(session, specs)
            earnings = await safe_earnings_event(session, symbol, as_of.date())

        rows = select_material_strikes(aggregate_gex_by_strike(contracts, price), price)
        if not rows:
            raise LookupError(
                f"No usable GEX data returned for {symbol} {requested_expiration}"
            )
        return GexStrikeSnapshot(
            symbol=symbol,
            description=equity.short_description or equity.description,
            price=price,
            change=change,
            change_percent=change_percent,
            as_of=as_of,
            expiration_date=requested_expiration,
            rows=rows,
            contracts_received=received,
            contracts_requested=requested,
            earnings_date=earnings.report_date,
            earnings_confirmed=earnings.confirmed,
            earnings_calculated=earnings.calculated,
        )

    async def history_snapshots(
        self,
        raw_symbol: str,
        expiration_dates: tuple[date, ...],
    ) -> list[GexStrikeSnapshot]:
        """Capture complete strike data for several fixed expirations in one stream."""
        symbol = normalize_symbol(raw_symbol)
        as_of = datetime.now(PACIFIC)
        requested_dates = {value for value in expiration_dates if value >= as_of.date()}
        if not requested_dates:
            return []

        async with Session(self.provider_secret, self.refresh_token) as session:
            equity = await Equity.get(session, symbol)
            chains, trade = await asyncio.gather(
                NestedOptionChain.get(session, symbol),
                self._trade_snapshot(session, equity.streamer_symbol),
            )
            today_id = (as_of.date() - date(1970, 1, 1)).days
            if trade.day_id != today_id:
                raise LookupError(f"No current-session trade was returned for {symbol}")
            price, change, change_percent = trade_values(trade)
            available_dates = {
                expiration.expiration_date
                for chain in chains
                for expiration in chain.expirations
                if expiration.expiration_date in requested_dates
                and expiration.expiration_type.lower() == "regular"
            }
            missing_dates = requested_dates - available_dates
            if missing_dates:
                LOGGER.warning(
                    "%s is missing tracked regular expirations: %s",
                    symbol,
                    ", ".join(value.isoformat() for value in sorted(missing_dates)),
                )
            if not available_dates:
                raise LookupError(f"No tracked monthly expirations are available for {symbol}")

            specs = build_contract_specs(
                chains,
                expiration_dates=available_dates,
                spot_price=price,
                strike_limit=None,
            )
            contracts, received, requested = await collect_gex_inputs(session, specs)

        description = equity.short_description or equity.description
        snapshots = []
        for expiration_date in sorted(available_dates):
            expiration_contracts = [
                contract
                for contract in contracts
                if contract.expiration_date == expiration_date
            ]
            rows = aggregate_gex_by_strike(expiration_contracts, price)
            if not rows:
                LOGGER.warning(
                    "No usable historical GEX rows for %s %s",
                    symbol,
                    expiration_date,
                )
                continue
            snapshots.append(
                GexStrikeSnapshot(
                    symbol=symbol,
                    description=description,
                    price=price,
                    change=change,
                    change_percent=change_percent,
                    as_of=as_of,
                    expiration_date=expiration_date,
                    rows=rows,
                    contracts_received=received,
                    contracts_requested=requested,
                )
            )
        return snapshots

    @staticmethod
    async def _trade_snapshot(session: Session, streamer_symbol: str) -> Trade:
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Trade, [streamer_symbol])

            async def receive() -> Trade:
                async for trade in streamer.listen(Trade):
                    if trade.event_symbol == streamer_symbol:
                        return trade
                raise LookupError("Trade stream closed before returning a price")

            try:
                return await asyncio.wait_for(receive(), timeout=12)
            except TimeoutError as exc:
                raise LookupError("Timed out waiting for the underlying price") from exc


async def safe_earnings_event(
    session: Session,
    symbol: str,
    as_of: date,
) -> EarningsEvent:
    """Keep a provider earnings failure from suppressing an otherwise valid chart."""
    try:
        return await earnings_event_for_symbol(session, symbol, as_of)
    except Exception:
        LOGGER.warning("Could not resolve earnings for GEX symbol %s", symbol, exc_info=True)
        return EarningsEvent(symbol=symbol, report_date=None)


def trade_values(trade: Trade) -> tuple[float, float | None, float | None]:
    price = finite_float(trade.price)
    change = finite_float(trade.change)
    if price is None or price <= 0:
        raise LookupError("No usable underlying price was returned")
    if change is None or price - change <= 0:
        return price, change, None
    return price, change, change / (price - change)


def choose_overview_expirations(
    chains: list[NestedOptionChain],
) -> list[NestedOptionChainExpiration]:
    by_date: dict[date, NestedOptionChainExpiration] = {}
    for chain in chains:
        for expiration in chain.expirations:
            if expiration.days_to_expiration >= 0:
                by_date.setdefault(expiration.expiration_date, expiration)
    ordered = sorted(by_date.values(), key=lambda item: item.expiration_date)
    if not ordered:
        raise LookupError("No future option expirations were returned")
    if len(ordered) <= MAX_OVERVIEW_EXPIRATIONS:
        return ordered

    selected = ordered[:NEAR_TERM_EXPIRATIONS]
    selected_dates = {item.expiration_date for item in selected}
    regular = [
        item
        for item in ordered
        if item.expiration_type.lower() == "regular"
        and item.expiration_date not in selected_dates
    ]
    remaining = MAX_OVERVIEW_EXPIRATIONS - len(selected)
    if len(regular) <= remaining:
        selected.extend(regular)
    else:
        selected.extend(evenly_spaced(regular, remaining))
    return sorted(selected, key=lambda item: item.expiration_date)


def evenly_spaced(items: list[NestedOptionChainExpiration], count: int):
    if count <= 0:
        return []
    if count >= len(items):
        return items
    if count == 1:
        return [items[-1]]
    indices = {round(index * (len(items) - 1) / (count - 1)) for index in range(count)}
    return [items[index] for index in sorted(indices)]


def build_contract_specs(
    chains: list[NestedOptionChain],
    *,
    expiration_dates: set[date],
    spot_price: float,
    strike_limit: int | None,
) -> list[ContractSpec]:
    specs: dict[str, ContractSpec] = {}
    for chain in chains:
        multiplier = chain.shares_per_contract or 100
        for expiration in chain.expirations:
            if expiration.expiration_date not in expiration_dates:
                continue
            strikes = expiration.strikes
            if strike_limit is not None and len(strikes) > strike_limit:
                strikes = sorted(
                    strikes,
                    key=lambda strike: abs(float(strike.strike_price) - spot_price),
                )[:strike_limit]
            for strike in strikes:
                strike_price = float(strike.strike_price)
                specs[strike.call_streamer_symbol] = ContractSpec(
                    strike.call_streamer_symbol,
                    expiration.expiration_date,
                    strike_price,
                    True,
                    multiplier,
                )
                specs[strike.put_streamer_symbol] = ContractSpec(
                    strike.put_streamer_symbol,
                    expiration.expiration_date,
                    strike_price,
                    False,
                    multiplier,
                )
    if not specs:
        raise LookupError("No option contracts were returned for the requested view")
    return list(specs.values())


async def collect_gex_inputs(
    session: Session, specs: list[ContractSpec]
) -> tuple[list[OptionGexInput], int, int]:
    specs_by_symbol = {spec.streamer_symbol: spec for spec in specs}
    all_symbols = set(specs_by_symbol)
    async with DXLinkStreamer(session) as streamer:
        await subscribe_in_batches(streamer, Summary, all_symbols)
        summaries = await collect_events(streamer, Summary, all_symbols, timeout=25)
        await streamer.unsubscribe_all(Summary)

        positive_oi = {
            symbol: summary.open_interest
            for symbol, summary in summaries.items()
            if summary.open_interest > 0
        }
        if not positive_oi:
            raise LookupError("Tastytrade returned no open interest for this option chain")

        await subscribe_in_batches(streamer, Greeks, positive_oi)
        greeks = await collect_events(streamer, Greeks, set(positive_oi), timeout=30)

    contracts = []
    for symbol, open_interest in positive_oi.items():
        greek = greeks.get(symbol)
        if greek is None:
            continue
        gamma = finite_float(greek.gamma)
        if gamma is None or gamma < 0:
            continue
        spec = specs_by_symbol[symbol]
        contracts.append(
            OptionGexInput(
                expiration_date=spec.expiration_date,
                strike=spec.strike,
                is_call=spec.is_call,
                gamma=gamma,
                open_interest=open_interest,
                multiplier=spec.multiplier,
            )
        )

    requested = len(positive_oi)
    received = len(contracts)
    if received < 2 or received / requested < 0.65:
        raise LookupError(
            f"Only {received}/{requested} open-interest contracts returned usable gamma; "
            "try again shortly"
        )
    return contracts, received, requested


async def subscribe_in_batches(
    streamer: DXLinkStreamer,
    event_type: type[Summary] | type[Greeks] | type[Trade],
    symbols: set[str] | dict[str, int],
) -> None:
    for batch in batched_strings(symbols, STREAM_SUBSCRIPTION_BATCH):
        await streamer.subscribe(event_type, batch, refresh_interval=1.0)


async def collect_events(streamer, event_type, targets: set[str], *, timeout: float):
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


def batched_strings(items, size: int):
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch
