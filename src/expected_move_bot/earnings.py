from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

TRACKED_EARNINGS_SYMBOLS = (
    "AAPL",
    "AVGO",
    "AMD",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "PLTR",
    "TSLA",
    "COIN",
    "MSTR",
    "CRWD",
    "MSFT",
    "ASML",
    "GS",
    "JPM",
    "BRK",
    "CRM",
    "NOW",
    "BABA",
    "DDOG",
    "SNOW",
    "MDB",
    "DELL",
    "FTNT",
    "HOOD",
    "INTC",
    "MU",
    "SNDK",
    "ORCL",
    "PANW",
    "SOFI",
    "SPCX",
    "SKHY",
    "TSM",
    "VST",
    "V",
    "MA",
    "AXP",
    "ZS",
    "NET",
    "COST",
    "AMAT",
    "LRCX",
)

EARNINGS_PROVIDER_SYMBOLS = {"BRK": "BRK/B"}


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    report_date: date | None
    market_cap: float | None = None
    confirmed: bool = False
    calculated: bool = False

    def days_until(self, as_of: date) -> int | None:
        if self.report_date is None:
            return None
        return (self.report_date - as_of).days


@dataclass(frozen=True)
class EarningsSnapshot:
    as_of: date
    events: list[EarningsEvent]


def sort_earnings_events(events: list[EarningsEvent]) -> list[EarningsEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.market_cap is None,
            -(event.market_cap or 0),
            event.symbol,
        ),
    )


def estimate_earnings_date(history: list[date], as_of: date) -> date | None:
    """Estimate the next report, with an 89-day last-report fallback."""
    prior_dates = sorted({report_date for report_date in history if report_date < as_of})
    if not prior_dates:
        return None

    if len(prior_dates) >= 4:
        # Four reports back represents the comparable fiscal quarter. Adding
        # 364 days preserves its weekday, which is usually stable.
        prior_year_candidate = prior_dates[-4] + timedelta(days=364)

        recent_dates = prior_dates[-8:]
        quarterly_intervals = [
            (current - previous).days
            for previous, current in zip(recent_dates, recent_dates[1:], strict=False)
            if 70 <= (current - previous).days <= 115
        ]
        if len(quarterly_intervals) >= 2:
            recent_candidate = prior_dates[-1] + timedelta(
                days=round(median(quarterly_intervals))
            )
            if (
                prior_year_candidate > as_of
                and recent_candidate > as_of
                and abs((prior_year_candidate - recent_candidate).days) <= 7
            ):
                return prior_year_candidate

    fallback_candidate = prior_dates[-1] + timedelta(days=89)
    return fallback_candidate if fallback_candidate > as_of else None


def format_earnings(snapshot: EarningsSnapshot) -> str:
    lines = [
        f"{'Ticker':^6} {'Stat':^4} {'Cap':^6}  {'Date':^9}  {'DTE':^3} ",
        f"{'-' * 6} {'-' * 4} {'-' * 6}  {'-' * 9}  {'-' * 3} ",
    ]
    for event in snapshot.events:
        # Emoji occupy two visual columns in Discord. Matching them with two
        # literal spaces keeps the rest of every row aligned.
        confirmation = "✅" if event.confirmed else "  "
        days = event.days_until(snapshot.as_of)
        if days is not None and days < 12:
            urgency = "‼️"
        elif days is not None and days < 22:
            urgency = "❗"
        else:
            urgency = "  "
        if confirmation != "  " and urgency != "  ":
            status = f"{confirmation}{urgency}"
        elif confirmation != "  ":
            status = f"{confirmation}  "
        elif urgency != "  ":
            status = f"{urgency}  "
        else:
            status = "    "
        market_cap = format_market_cap(event.market_cap)
        if event.report_date is None:
            earnings = "N/A"
            countdown = "-"
        else:
            estimate_prefix = "~" if event.calculated else " "
            earnings = f"{estimate_prefix}{event.report_date:%m/%d/%y}"
            countdown = str(days)
        lines.append(
            f"{event.symbol:<6} {status} "
            f"{market_cap:>6}  {earnings:>9}  {countdown:^3} "
        )
    return f"```\n{'\n'.join(lines)}\n```"


def format_earnings_lee(snapshot: EarningsSnapshot) -> str:
    """Render the original proportional-text earnings layout."""
    lines = []
    for event in snapshot.events:
        confirmation = " ✅" if event.confirmed else ""
        days = event.days_until(snapshot.as_of)
        if days is not None and days < 12:
            urgency = " ‼️"
        elif days is not None and days < 22:
            urgency = " ❗"
        else:
            urgency = ""
        market_cap = format_market_cap_lee(event.market_cap)
        if event.report_date is None:
            lines.append(
                f"**{event.symbol}**{confirmation}{urgency} • "
                f"{market_cap} • Date unavailable"
            )
            continue

        estimate_prefix = "~ " if event.calculated else ""
        if days == 0:
            countdown = "Today"
        elif days == 1:
            countdown = "1 day"
        else:
            countdown = f"{days} days"
        date_text = f"{event.report_date:%b} {event.report_date.day}, {event.report_date.year}"
        lines.append(
            f"**{event.symbol}**{confirmation}{urgency} • {market_cap} • "
            f"{estimate_prefix}{date_text} • {countdown}"
        )
    return "\n".join(lines)


def format_market_cap(value: float | None) -> str:
    if value is None:
        return "N/A"
    absolute = abs(value)
    if absolute >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.0f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    return f"{value:,.0f}"


def format_market_cap_lee(value: float | None) -> str:
    if value is None:
        return "Market cap unavailable"
    absolute = abs(value)
    if absolute >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"
