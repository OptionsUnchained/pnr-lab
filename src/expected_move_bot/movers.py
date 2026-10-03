from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
MARKET_CAP_MINIMUM = 20_000_000_000
MOVERS_LIMIT = 15


class MoversMode(StrEnum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTER_MARKET = "after-market"


@dataclass(frozen=True)
class ScheduledMoversReport:
    mode: MoversMode
    label: str


MOVERS_SCHEDULE = {
    time(6, 15): ScheduledMoversReport(MoversMode.PREMARKET, "Premarket"),
    time(6, 45): ScheduledMoversReport(MoversMode.REGULAR, "Regular Session"),
    time(8, 0): ScheduledMoversReport(MoversMode.REGULAR, "Regular Session"),
    time(11, 0): ScheduledMoversReport(MoversMode.REGULAR, "Regular Session"),
    time(12, 30): ScheduledMoversReport(MoversMode.REGULAR, "Regular Session"),
    time(13, 30): ScheduledMoversReport(MoversMode.AFTER_MARKET, "After Market"),
}


@dataclass(frozen=True)
class MarketMover:
    symbol: str
    price: float
    change: float
    change_percent: float
    market_cap: float


@dataclass(frozen=True)
class MarketMoversSnapshot:
    as_of: datetime
    gainers: list[MarketMover]
    losers: list[MarketMover]
    eligible_count: int
    quoted_count: int
    mode: MoversMode = MoversMode.REGULAR


def scheduled_report(now: datetime) -> ScheduledMoversReport | None:
    """Return the report configuration for an exact Pacific-time minute."""
    local = now.astimezone(PACIFIC)
    if local.weekday() >= 5:
        return None
    return MOVERS_SCHEDULE.get(local.time().replace(second=0, microsecond=0))


def scheduled_report_label(now: datetime) -> str | None:
    """Return the scheduled label; retained as a small public convenience."""
    report = scheduled_report(now)
    return report.label if report is not None else None


def mode_label(mode: MoversMode) -> str:
    return {
        MoversMode.PREMARKET: "Premarket",
        MoversMode.REGULAR: "Regular Session",
        MoversMode.AFTER_MARKET: "After Market",
    }[mode]


def comparison_label(mode: MoversMode) -> str:
    return {
        MoversMode.PREMARKET: "Last premarket trade vs prior close",
        MoversMode.REGULAR: "Latest regular trade vs prior close",
        MoversMode.AFTER_MARKET: "Last after-hours trade vs today's close",
    }[mode]


def rank_market_movers(
    movers: list[MarketMover], limit: int = MOVERS_LIMIT
) -> tuple[list[MarketMover], list[MarketMover]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    gainers = sorted(
        (mover for mover in movers if mover.change_percent > 0),
        key=lambda mover: mover.change_percent,
        reverse=True,
    )[:limit]
    losers = sorted(
        (mover for mover in movers if mover.change_percent < 0),
        key=lambda mover: mover.change_percent,
    )[:limit]
    return gainers, losers


def format_market_cap(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    return f"${value / 1_000_000_000:.1f}B"


def format_movers(movers: list[MarketMover]) -> str:
    if not movers:
        return "No qualifying movers were available."
    return "\n".join(
        f"**{rank}. {mover.symbol}**  **{mover.change_percent:+.2%}**\n"
        f"`{format_market_cap(mover.market_cap)} · ${mover.price:,.2f}`"
        for rank, mover in enumerate(movers, start=1)
    )
