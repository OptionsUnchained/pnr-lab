from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class ContractFlow:
    strike: float
    is_call: bool
    volume: int
    open_interest: int
    turnover: float
    buy_volume: int = 0
    sell_volume: int = 0
    multiplier: int = 100

    @property
    def unclassified_volume(self) -> int:
        return max(0, self.volume - self.buy_volume - self.sell_volume)

    @property
    def premium(self) -> float:
        return self.turnover * self.multiplier


@dataclass(frozen=True)
class StrikeFlowRow:
    strike: float
    call_volume: int
    put_volume: int
    call_buy: int
    call_sell: int
    put_buy: int
    put_sell: int
    unclassified: int
    open_interest: int
    premium: float

    @property
    def volume(self) -> int:
        return self.call_volume + self.put_volume

    @property
    def volume_oi(self) -> float | None:
        return self.volume / self.open_interest if self.open_interest > 0 else None


@dataclass(frozen=True)
class OptionsFlowSnapshot:
    symbol: str
    description: str
    price: float
    change: float | None
    change_percent: float | None
    as_of: datetime
    session_date: date
    expiration_date: date
    rows: tuple[StrikeFlowRow, ...]

    @property
    def total_volume(self) -> int:
        return sum(row.volume for row in self.rows)

    @property
    def total_premium(self) -> float:
        return sum(row.premium for row in self.rows)

    @property
    def classified_volume(self) -> int:
        return sum(
            row.call_buy + row.call_sell + row.put_buy + row.put_sell
            for row in self.rows
        )

    @property
    def classified_coverage(self) -> float:
        return self.classified_volume / self.total_volume if self.total_volume else 0.0

    @property
    def bullish_volume(self) -> int:
        # Calls lifted at the ask and puts sold at the bid are bullish proxies.
        return sum(row.call_buy + row.put_sell for row in self.rows)

    @property
    def bearish_volume(self) -> int:
        # Puts lifted at the ask and calls sold at the bid are bearish proxies.
        return sum(row.put_buy + row.call_sell for row in self.rows)

    @property
    def directional_bias(self) -> float:
        directional = self.bullish_volume + self.bearish_volume
        if not directional:
            return 0.0
        return (self.bullish_volume - self.bearish_volume) / directional


def scale_sides(volume: int, buy_volume: float, sell_volume: float) -> tuple[int, int]:
    """Keep bid/ask classified volume inside the authoritative Trade day volume."""
    buy = max(0.0, buy_volume)
    sell = max(0.0, sell_volume)
    side_total = buy + sell
    if volume <= 0 or side_total <= 0:
        return 0, 0
    factor = min(1.0, volume / side_total)
    scaled_buy = round(buy * factor)
    scaled_sell = min(volume - scaled_buy, round(sell * factor))
    return max(0, scaled_buy), max(0, scaled_sell)


def top_strikes(contracts: list[ContractFlow], limit: int = 10) -> list[float]:
    totals: dict[float, int] = {}
    for contract in contracts:
        totals[contract.strike] = totals.get(contract.strike, 0) + contract.volume
    ranked = sorted(totals, key=lambda strike: (-totals[strike], strike))
    return ranked[:limit]


def aggregate_top_strikes(
    contracts: list[ContractFlow], limit: int = 10
) -> tuple[StrikeFlowRow, ...]:
    selected = set(top_strikes(contracts, limit))
    rows = []
    for strike in selected:
        values = [contract for contract in contracts if contract.strike == strike]
        calls = [contract for contract in values if contract.is_call]
        puts = [contract for contract in values if not contract.is_call]
        rows.append(
            StrikeFlowRow(
                strike=strike,
                call_volume=sum(item.volume for item in calls),
                put_volume=sum(item.volume for item in puts),
                call_buy=sum(item.buy_volume for item in calls),
                call_sell=sum(item.sell_volume for item in calls),
                put_buy=sum(item.buy_volume for item in puts),
                put_sell=sum(item.sell_volume for item in puts),
                unclassified=sum(item.unclassified_volume for item in values),
                open_interest=sum(item.open_interest for item in values),
                premium=sum(item.premium for item in values),
            )
        )
    return tuple(sorted(rows, key=lambda row: (-row.volume, row.strike)))


def flow_bias_label(value: float) -> str:
    magnitude = abs(value)
    if magnitude < 0.10:
        strength = "Balanced"
    elif magnitude < 0.30:
        strength = "Slightly"
    elif magnitude < 0.60:
        strength = "Moderately"
    else:
        strength = "Strongly"
    if strength == "Balanced":
        return strength
    return f"{strength} {'bullish' if value > 0 else 'bearish'}"
