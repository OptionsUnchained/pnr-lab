from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image

from expected_move_bot.gex import (
    ExpiryGexRow,
    GexExpirySnapshot,
    GexStrikeSnapshot,
    StrikeGexRow,
)
from expected_move_bot.gex_image import (
    HEIGHT,
    WIDTH,
    earnings_header,
    expiry_label_style,
    render_gex_expiry,
    render_gex_strikes,
    strike_tick_values,
)


def test_render_gex_expiry_returns_square_png() -> None:
    snapshot = GexExpirySnapshot(
        symbol="IWM",
        description="iShares Russell 2000 ETF",
        price=285.52,
        change=-1.63,
        change_percent=-0.0057,
        as_of=datetime(2026, 9, 18, 12, tzinfo=ZoneInfo("America/Los_Angeles")),
        rows=[
            ExpiryGexRow(date(2026, 9, 25), 220_000_000, -1_300_000_000),
            ExpiryGexRow(date(2026, 10, 16), 90_000_000, -420_000_000),
            ExpiryGexRow(date(2026, 11, 20), 150_000_000, -200_000_000),
        ],
        contracts_received=450,
        contracts_requested=500,
    )

    image = Image.open(BytesIO(render_gex_expiry(snapshot)))

    assert image.format == "PNG"
    assert image.size == (WIDTH, HEIGHT)


def test_render_gex_strikes_returns_square_png() -> None:
    rows = [
        StrikeGexRow(
            strike=float(strike),
            call_gex=max(0, (strike - 150) * 20_000),
            put_gex=-max(0, (190 - strike) * 14_000),
            call_open_interest=max(0, strike - 130) * 10,
            put_open_interest=max(0, 210 - strike) * 8,
        )
        for strike in range(130, 231, 5)
    ]
    snapshot = GexStrikeSnapshot(
        symbol="OKTA",
        description="Okta Inc - Class A",
        price=187.85,
        change=21.35,
        change_percent=0.1282,
        as_of=datetime(2026, 9, 18, 12, tzinfo=ZoneInfo("America/Los_Angeles")),
        expiration_date=date(2026, 10, 16),
        rows=rows,
        contracts_received=42,
        contracts_requested=46,
    )

    image = Image.open(BytesIO(render_gex_strikes(snapshot)))

    assert image.format == "PNG"
    assert image.size == (WIDTH, HEIGHT)


def test_strike_ticks_use_ten_dollar_intervals_for_normal_stock_range() -> None:
    assert strike_tick_values(132.5, 237.5) == [
        140,
        150,
        160,
        170,
        180,
        190,
        200,
        210,
        220,
        230,
    ]


def test_strike_ticks_adapt_for_low_priced_stock() -> None:
    assert strike_tick_values(7.5, 22.5) == [
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
    ]


def test_expiry_labels_rotate_as_the_chart_gets_denser() -> None:
    assert expiry_label_style(70) == (23, 45)
    assert expiry_label_style(45) == (18, 65)
    assert expiry_label_style(24) == (15, 90)


def test_earnings_header_shows_confirmation_and_dte() -> None:
    assert earnings_header(
        date(2026, 11, 20),
        date(2026, 9, 18),
        confirmed=True,
        calculated=False,
    ) == "EARNINGS · NOV 20, 2026 ✓ · 63 DTE"


def test_earnings_header_marks_historical_estimate() -> None:
    assert earnings_header(
        date(2026, 11, 20),
        date(2026, 9, 18),
        confirmed=False,
        calculated=True,
    ) == "EARNINGS · ~ NOV 20, 2026 · 63 DTE"
