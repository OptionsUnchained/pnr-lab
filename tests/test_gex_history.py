from datetime import date, datetime
from zoneinfo import ZoneInfo

from expected_move_bot.gex import StrikeGexRow
from expected_move_bot.gex_history import (
    GexCaptureReport,
    GexCaptureStatus,
    GexHistoryPoint,
    format_gex_collection_section,
    format_gex_history_table,
    ranked_walls,
    should_capture_gex_history,
)


def test_ranked_walls_keeps_top_three_on_each_side() -> None:
    rows = [
        StrikeGexRow(580, 1_000, -9_000, 10, 90),
        StrikeGexRow(600, 4_000, -3_000, 40, 30),
        StrikeGexRow(620, 8_000, -1_000, 80, 10),
        StrikeGexRow(640, 6_000, -5_000, 60, 50),
    ]

    calls, puts = ranked_walls(rows)

    assert [wall.strike for wall in calls] == [620, 640, 600]
    assert [wall.strike for wall in puts] == [580, 640, 600]


def test_capture_window_runs_once_at_645_pacific_on_weekdays() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 9, 21, 6, 45, tzinfo=pacific)

    assert should_capture_gex_history(now, None)
    assert not should_capture_gex_history(now, now.date())
    assert not should_capture_gex_history(now.replace(hour=6, minute=44), None)
    assert not should_capture_gex_history(
        datetime(2026, 9, 20, 6, 45, tzinfo=pacific),
        None,
    )


def test_history_table_is_compact_and_contains_bias_and_walls() -> None:
    point = GexHistoryPoint(
        snapshot_date=date(2026, 9, 21),
        captured_at=datetime(2026, 9, 21, 6, 45, tzinfo=ZoneInfo("America/Los_Angeles")),
        symbol="META",
        expiration_date=date(2026, 11, 20),
        expiration_dte=60,
        spot_price=665.38,
        total_call_gex=180_000_000,
        total_put_gex=-40_000_000,
        net_gex=140_000_000,
        gross_gex=220_000_000,
        bias=0.55,
        bias_label="Moderately Positive",
        call_wall_strike=700.0,
        second_call_wall_strike=800.0,
        third_call_wall_strike=750.0,
        put_wall_strike=585.0,
        second_put_wall_strike=600.0,
        third_put_wall_strike=620.0,
    )

    assert format_gex_history_table([point]).splitlines() == [
        "```",
        "Date     Price   Bias    PutW   CallW   Call2",
        "----- -------- ------ ------- ------- -------",
        "09/21   665.38   +55%     585     700     800",
        "```",
    ]


def test_collection_section_shows_complete_partial_and_failed_pulls() -> None:
    expiration = date(2026, 11, 20)
    report = GexCaptureReport(
        captured_at=datetime(2026, 9, 21, 6, 45, tzinfo=ZoneInfo("America/Los_Angeles")),
        statuses=(
            GexCaptureStatus("NVDA", expiration, True, 0.55, 300, 300),
            GexCaptureStatus("META", expiration, True, -0.31, 298, 300),
            GexCaptureStatus("AAPL", expiration, False, error="No data returned"),
        ),
    )

    assert report.saved_count == 2
    assert report.complete_count == 1
    assert report.expected_count == 3
    assert format_gex_collection_section(report, expiration).splitlines() == [
        "✅ **NVDA** · +55% · 300/300 contracts",
        "⚠️ **META** · -31% · 298/300 contracts",
        "❌ **AAPL** · failed",
    ]
