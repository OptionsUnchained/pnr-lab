from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from expected_move_bot.epr import EprFetchResult, EprSnapshot
from expected_move_bot.epr_watchlist import (
    EPR_WATCHLIST_SYMBOLS,
    EprHistoryPoint,
    build_epr_watchlist_report,
    format_epr_watchlist,
    should_capture_epr_watchlist,
)


def test_epr_watchlist_runs_once_at_631_pacific_on_weekdays() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 10, 5, 6, 31, tzinfo=pacific)

    assert should_capture_epr_watchlist(now, None)
    assert not should_capture_epr_watchlist(now, now.date())
    assert not should_capture_epr_watchlist(now.replace(minute=30), None)
    assert not should_capture_epr_watchlist(
        datetime(2026, 10, 4, 6, 31, tzinfo=pacific),
        None,
    )


def test_epr_watchlist_marks_changes_and_explains_direction() -> None:
    captured_at = datetime(
        2026,
        10,
        5,
        6,
        31,
        tzinfo=ZoneInfo("America/Los_Angeles"),
    )
    results = (
        EprFetchResult("AAPL", EprSnapshot("AAPL", Decimal("15"), Decimal("10"))),
        EprFetchResult("META", EprSnapshot("META", Decimal("18"), Decimal("12"))),
    )
    previous = {
        "AAPL": EprHistoryPoint(date(2026, 10, 2), "AAPL", Decimal("14"), Decimal("11")),
        "META": EprHistoryPoint(date(2026, 10, 2), "META", Decimal("18"), Decimal("12")),
    }

    report = build_epr_watchlist_report(
        ("AAPL", "META"),
        results,
        previous,
        captured_at,
    )
    output = format_epr_watchlist(report)

    assert report.changed_count == 1
    assert "Changes (1):" in output
    assert "**AAPL** · Down +1 pp · Up -1 pp" in output
    assert "AAPL     -15%   +10%" in output
    assert ".00%" not in output
    assert "META" in output


def test_complete_watchlist_report_fits_in_one_discord_embed() -> None:
    captured_at = datetime(
        2026,
        10,
        5,
        6,
        31,
        tzinfo=ZoneInfo("America/Los_Angeles"),
    )
    results = tuple(
        EprFetchResult(symbol, EprSnapshot(symbol, Decimal("15"), Decimal("10")))
        for symbol in EPR_WATCHLIST_SYMBOLS
    )
    previous = {
        symbol: EprHistoryPoint(
            date(2026, 10, 2),
            symbol,
            Decimal("14"),
            Decimal("11"),
        )
        for symbol in EPR_WATCHLIST_SYMBOLS
    }
    report = build_epr_watchlist_report(
        EPR_WATCHLIST_SYMBOLS,
        results,
        previous,
        captured_at,
    )

    assert len(format_epr_watchlist(report)) < 4096


def test_epr_watchlist_is_alphabetical_and_includes_index_etfs() -> None:
    assert tuple(sorted(EPR_WATCHLIST_SYMBOLS)) == EPR_WATCHLIST_SYMBOLS
    assert len(EPR_WATCHLIST_SYMBOLS) == 47
    assert {"SPY", "QQQ", "SMH"} <= set(EPR_WATCHLIST_SYMBOLS)
