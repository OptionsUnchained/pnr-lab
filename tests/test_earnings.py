from datetime import date

from expected_move_bot.earnings import (
    EarningsEvent,
    EarningsSnapshot,
    estimate_earnings_date,
    format_earnings,
    format_earnings_lee,
    format_market_cap,
    format_market_cap_lee,
    sort_earnings_events,
)


def test_sort_earnings_events_orders_by_market_cap_descending() -> None:
    events = [
        EarningsEvent("AAPL", None, market_cap=3_000_000_000_000),
        EarningsEvent("NVDA", date(2026, 11, 18), market_cap=4_000_000_000_000),
        EarningsEvent("AMD", date(2026, 10, 27), market_cap=350_000_000_000),
        EarningsEvent("SPCX", None),
    ]

    assert [event.symbol for event in sort_earnings_events(events)] == [
        "NVDA",
        "AAPL",
        "AMD",
        "SPCX",
    ]


def test_format_earnings_shows_countdown_and_only_confirmed_check() -> None:
    snapshot = EarningsSnapshot(
        as_of=date(2026, 9, 18),
        events=[
            EarningsEvent(
                "AAPL",
                date(2026, 9, 18),
                market_cap=3_800_000_000_000,
                confirmed=True,
            ),
            EarningsEvent("AMD", date(2026, 10, 5), market_cap=350_000_000_000),
            EarningsEvent(
                "NVDA",
                date(2026, 10, 18),
                market_cap=4_200_000_000_000,
                calculated=True,
            ),
            EarningsEvent("PLTR", None, market_cap=410_000_000_000),
        ],
    )

    assert format_earnings(snapshot).splitlines() == [
        "```",
        "Ticker Stat  Cap      Date     DTE ",
        "------ ---- ------  ---------  --- ",
        "AAPL   ✅‼️  3.80T   09/18/26   0  ",
        "AMD    ❗     350B   10/05/26  17  ",
        "NVDA         4.20T  ~10/18/26  30  ",
        "PLTR          410B        N/A   -  ",
        "```",
    ]


def test_format_market_cap() -> None:
    assert format_market_cap(3_854_000_000_000) == "3.85T"
    assert format_market_cap(245_600_000_000) == "246B"
    assert format_market_cap(850_000_000) == "850M"
    assert format_market_cap(None) == "N/A"


def test_format_earnings_lee_matches_original_layout() -> None:
    snapshot = EarningsSnapshot(
        as_of=date(2026, 9, 18),
        events=[
            EarningsEvent(
                "AAPL",
                date(2026, 9, 18),
                market_cap=3_800_000_000_000,
                confirmed=True,
            ),
            EarningsEvent("AMD", date(2026, 10, 5), market_cap=350_000_000_000),
            EarningsEvent(
                "NVDA",
                date(2026, 10, 18),
                market_cap=4_200_000_000_000,
                calculated=True,
            ),
            EarningsEvent("PLTR", None, market_cap=410_000_000_000),
        ],
    )

    assert format_earnings_lee(snapshot).splitlines() == [
        "**AAPL** ✅ ‼️ • $3.80T • Sep 18, 2026 • Today",
        "**AMD** ❗ • $350.0B • Oct 5, 2026 • 17 days",
        "**NVDA** • $4.20T • ~ Oct 18, 2026 • 30 days",
        "**PLTR** • $410.0B • Date unavailable",
    ]


def test_format_market_cap_lee() -> None:
    assert format_market_cap_lee(3_854_000_000_000) == "$3.85T"
    assert format_market_cap_lee(245_600_000_000) == "$245.6B"
    assert format_market_cap_lee(None) == "Market cap unavailable"


def test_estimate_earnings_date_uses_prior_year_when_methods_agree() -> None:
    history = [
        date(2025, 10, 30),
        date(2026, 1, 29),
        date(2026, 4, 30),
        date(2026, 7, 30),
    ]

    assert estimate_earnings_date(history, date(2026, 9, 18)) == date(2026, 10, 29)


def test_estimate_earnings_date_uses_89_day_fallback_when_methods_disagree() -> None:
    history = [
        date(2025, 10, 30),
        date(2026, 1, 1),
        date(2026, 4, 1),
        date(2026, 7, 1),
    ]

    assert estimate_earnings_date(history, date(2026, 9, 18)) == date(2026, 9, 28)


def test_estimate_earnings_date_uses_89_day_fallback_with_short_history() -> None:
    history = [date(2026, 1, 29), date(2026, 4, 30), date(2026, 7, 30)]

    assert estimate_earnings_date(history, date(2026, 9, 18)) == date(2026, 10, 27)


def test_estimate_earnings_date_rejects_past_89_day_fallback() -> None:
    history = [date(2026, 6, 1)]

    assert estimate_earnings_date(history, date(2026, 9, 18)) is None
