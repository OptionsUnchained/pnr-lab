from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class OptionGexInput:
    expiration_date: date
    strike: float
    is_call: bool
    gamma: float
    open_interest: int
    multiplier: int = 100


@dataclass(frozen=True)
class ExpiryGexRow:
    expiration_date: date
    call_gex: float
    put_gex: float

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex


@dataclass(frozen=True)
class StrikeGexRow:
    strike: float
    call_gex: float
    put_gex: float
    call_open_interest: int
    put_open_interest: int

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex

    @property
    def total_open_interest(self) -> int:
        return self.call_open_interest + self.put_open_interest

    @property
    def absolute_gex(self) -> float:
        return abs(self.call_gex) + abs(self.put_gex)


@dataclass(frozen=True)
class GexExpirySnapshot:
    symbol: str
    description: str
    price: float
    change: float | None
    change_percent: float | None
    as_of: datetime
    rows: list[ExpiryGexRow]
    contracts_received: int
    contracts_requested: int
    earnings_date: date | None = None
    earnings_confirmed: bool = False
    earnings_calculated: bool = False

    @property
    def total_gex(self) -> float:
        return sum(row.net_gex for row in self.rows)

    @property
    def gross_gex(self) -> float:
        return sum(abs(row.call_gex) + abs(row.put_gex) for row in self.rows)

    @property
    def gex_bias(self) -> float:
        return self.total_gex / self.gross_gex if self.gross_gex else 0.0


@dataclass(frozen=True)
class GexStrikeSnapshot:
    symbol: str
    description: str
    price: float
    change: float | None
    change_percent: float | None
    as_of: datetime
    expiration_date: date
    rows: list[StrikeGexRow]
    contracts_received: int
    contracts_requested: int
    earnings_date: date | None = None
    earnings_confirmed: bool = False
    earnings_calculated: bool = False

    @property
    def total_gex(self) -> float:
        return sum(row.net_gex for row in self.rows)

    @property
    def gross_gex(self) -> float:
        return sum(row.absolute_gex for row in self.rows)

    @property
    def gex_bias(self) -> float:
        return self.total_gex / self.gross_gex if self.gross_gex else 0.0


def gex_bias_label(bias: float) -> str:
    """Classify net GEX as a percentage of gross absolute GEX."""
    magnitude = abs(bias)
    if magnitude < 0.10:
        return "Balanced"
    direction = "Positive" if bias > 0 else "Negative"
    if magnitude < 0.30:
        return f"Slightly {direction}"
    if magnitude < 0.60:
        return f"Moderately {direction}"
    return f"Strongly {direction}"


def contract_gex(
    gamma: float,
    open_interest: int,
    spot_price: float,
    multiplier: int = 100,
) -> float:
    """Return dollar gamma exposure for a 1% move in the underlying."""
    if not math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be a finite non-negative number")
    if open_interest < 0:
        raise ValueError("open interest cannot be negative")
    if not math.isfinite(spot_price) or spot_price <= 0:
        raise ValueError("spot price must be positive")
    if multiplier <= 0:
        raise ValueError("contract multiplier must be positive")
    return gamma * open_interest * multiplier * spot_price**2 * 0.01


def aggregate_gex_by_expiry(
    contracts: list[OptionGexInput], spot_price: float
) -> list[ExpiryGexRow]:
    totals: dict[date, list[float]] = {}
    for contract in contracts:
        exposure = contract_gex(
            contract.gamma,
            contract.open_interest,
            spot_price,
            contract.multiplier,
        )
        call_put = totals.setdefault(contract.expiration_date, [0.0, 0.0])
        if contract.is_call:
            call_put[0] += exposure
        else:
            call_put[1] -= exposure
    return [
        ExpiryGexRow(expiration, values[0], values[1])
        for expiration, values in sorted(totals.items())
    ]


def aggregate_gex_by_strike(
    contracts: list[OptionGexInput], spot_price: float
) -> list[StrikeGexRow]:
    totals: dict[float, list[float | int]] = {}
    for contract in contracts:
        exposure = contract_gex(
            contract.gamma,
            contract.open_interest,
            spot_price,
            contract.multiplier,
        )
        values = totals.setdefault(contract.strike, [0.0, 0.0, 0, 0])
        if contract.is_call:
            values[0] = float(values[0]) + exposure
            values[2] = int(values[2]) + contract.open_interest
        else:
            values[1] = float(values[1]) - exposure
            values[3] = int(values[3]) + contract.open_interest
    return [
        StrikeGexRow(
            strike=strike,
            call_gex=float(values[0]),
            put_gex=float(values[1]),
            call_open_interest=int(values[2]),
            put_open_interest=int(values[3]),
        )
        for strike, values in sorted(totals.items())
    ]


def select_material_strikes(
    rows: list[StrikeGexRow],
    spot_price: float,
    *,
    core_count: int = 25,
    top_count: int = 15,
) -> list[StrikeGexRow]:
    """Trim empty tails without missing isolated high-OI or high-GEX strikes.

    The entire expiration is ranked before anything is removed. The output
    retains a core around spot, global OI/GEX leaders, and every strike inside
    the resulting outer bounds so the numerical strike axis stays continuous.
    """
    ordered = sorted(rows, key=lambda row: row.strike)
    if len(ordered) <= core_count:
        return ordered

    indexed = list(enumerate(ordered))
    keep: set[int] = set()

    nearest = sorted(indexed, key=lambda pair: abs(pair[1].strike - spot_price))
    keep.update(index for index, _ in nearest[:core_count])

    by_oi = sorted(indexed, key=lambda pair: pair[1].total_open_interest, reverse=True)
    by_gex = sorted(indexed, key=lambda pair: pair[1].absolute_gex, reverse=True)
    keep.update(index for index, row in by_oi[:top_count] if row.total_open_interest > 0)
    keep.update(index for index, row in by_gex[:top_count] if row.absolute_gex > 0)

    max_oi = max(row.total_open_interest for row in ordered)
    max_gex = max(row.absolute_gex for row in ordered)
    oi_threshold = max(25, math.ceil(max_oi * 0.02))
    gex_threshold = max_gex * 0.01
    keep.update(
        index
        for index, row in indexed
        if row.total_open_interest >= oi_threshold
        or (max_gex > 0 and row.absolute_gex >= gex_threshold)
    )

    left = max(0, min(keep) - 1)
    right = min(len(ordered) - 1, max(keep) + 1)
    return ordered[left : right + 1]
