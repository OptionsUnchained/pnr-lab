from datetime import datetime
from zoneinfo import ZoneInfo

from expected_move_bot.movers import (
    MarketMover,
    MoversMode,
    comparison_label,
    format_market_cap,
    format_movers,
    rank_market_movers,
    scheduled_report,
    scheduled_report_label,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


def mover(symbol: str, percent: float) -> MarketMover:
    return MarketMover(symbol, 100.0, percent * 100.0, percent, 25_000_000_000)


def test_rank_movers_separates_and_sorts() -> None:
    gainers, losers = rank_market_movers(
        [
            mover("FLAT", 0),
            mover("UP1", 0.01),
            mover("DOWN2", -0.02),
            mover("UP3", 0.03),
            mover("DOWN1", -0.01),
        ],
        limit=2,
    )
    assert [item.symbol for item in gainers] == ["UP3", "UP1"]
    assert [item.symbol for item in losers] == ["DOWN2", "DOWN1"]


def test_schedule_uses_pacific_time_and_skips_weekends() -> None:
    premarket = scheduled_report(datetime(2026, 9, 18, 6, 15, tzinfo=PACIFIC))
    assert premarket is not None
    assert premarket.mode == MoversMode.PREMARKET
    assert premarket.label == "Premarket"

    regular = scheduled_report(datetime(2026, 9, 18, 11, 0, tzinfo=PACIFIC))
    assert regular is not None
    assert regular.mode == MoversMode.REGULAR

    after_market = scheduled_report(datetime(2026, 9, 18, 13, 30, tzinfo=PACIFIC))
    assert after_market is not None
    assert after_market.mode == MoversMode.AFTER_MARKET
    assert scheduled_report_label(datetime(2026, 9, 18, 12, 30, tzinfo=PACIFIC)) == (
        "Regular Session"
    )
    assert scheduled_report(datetime(2026, 9, 19, 6, 15, tzinfo=PACIFIC)) is None
    assert scheduled_report(datetime(2026, 9, 18, 6, 16, tzinfo=PACIFIC)) is None


def test_comparison_labels_match_each_mode() -> None:
    assert comparison_label(MoversMode.PREMARKET) == "Last premarket trade vs prior close"
    assert comparison_label(MoversMode.REGULAR) == "Latest regular trade vs prior close"
    assert comparison_label(MoversMode.AFTER_MARKET) == (
        "Last after-hours trade vs today's close"
    )


def test_mover_formatting() -> None:
    text = format_movers([mover("NVDA", 0.0312)])
    assert "**1. NVDA**  **+3.12%**" in text
    assert "`$25.0B · $100.00`" in text
    assert "**1. DOWN**  **-2.00%**" in format_movers([mover("DOWN", -0.02)])
    assert format_market_cap(1_250_000_000_000) == "$1.25T"
