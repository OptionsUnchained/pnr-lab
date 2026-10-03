from datetime import date, datetime

import pytest
from PIL import Image

from expected_move_bot.options_flow import (
    ContractFlow,
    OptionsFlowSnapshot,
    aggregate_top_strikes,
    flow_bias_label,
    scale_sides,
    top_strikes,
)
from expected_move_bot.options_flow_image import render_options_flow


def contract(
    strike: float,
    is_call: bool,
    volume: int,
    *,
    buy: int = 0,
    sell: int = 0,
    oi: int = 100,
    turnover: float = 1_000,
) -> ContractFlow:
    return ContractFlow(strike, is_call, volume, oi, turnover, buy, sell)


def test_top_strikes_ranks_combined_call_and_put_volume() -> None:
    values = [
        contract(100, True, 600),
        contract(100, False, 500),
        contract(105, True, 900),
        contract(105, False, 10),
        contract(110, True, 100),
    ]

    assert top_strikes(values, limit=2) == [100, 105]


def test_aggregate_reports_sides_oi_premium_and_unclassified() -> None:
    values = [
        contract(100, True, 100, buy=60, sell=30, oi=200, turnover=500),
        contract(100, False, 80, buy=25, sell=35, oi=100, turnover=400),
    ]

    row = aggregate_top_strikes(values)[0]

    assert row.volume == 180
    assert (row.call_buy, row.call_sell) == (60, 30)
    assert (row.put_buy, row.put_sell) == (25, 35)
    assert row.unclassified == 30
    assert row.volume_oi == pytest.approx(0.6)
    assert row.premium == 90_000


def test_scale_sides_never_exceeds_day_volume() -> None:
    buy, sell = scale_sides(100, 80, 70)

    assert buy + sell <= 100
    assert buy / sell == pytest.approx(80 / 70, rel=0.03)


def sample_snapshot() -> OptionsFlowSnapshot:
    rows = aggregate_top_strikes(
        [
            contract(float(strike), True, 1_500 - strike, buy=800, sell=400)
            for strike in range(100, 110)
        ]
        + [
            contract(float(strike), False, 1_200 - strike, buy=300, sell=500)
            for strike in range(100, 110)
        ]
    )
    return OptionsFlowSnapshot(
        symbol="TEST",
        description="Test Company Common Stock",
        price=104.25,
        change=2.25,
        change_percent=0.022,
        as_of=datetime(2026, 9, 19, 10, 0),
        session_date=date(2026, 9, 18),
        expiration_date=date(2026, 11, 20),
        rows=rows,
    )


def test_directional_bias_uses_call_buys_and_put_sells_as_bullish() -> None:
    snapshot = sample_snapshot()

    assert snapshot.directional_bias > 0
    assert "bullish" in flow_bias_label(snapshot.directional_bias).lower()


def test_options_flow_image_renders_png() -> None:
    payload = render_options_flow(sample_snapshot())

    image = Image.open(__import__("io").BytesIO(payload))
    assert image.size == (1080, 1050)
    assert image.format == "PNG"
