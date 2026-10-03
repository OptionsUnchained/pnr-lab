from dataclasses import dataclass
from datetime import date, datetime

import pytest

from expected_move_bot.gex import (
    ExpiryGexRow,
    GexExpirySnapshot,
    OptionGexInput,
    StrikeGexRow,
    aggregate_gex_by_expiry,
    aggregate_gex_by_strike,
    contract_gex,
    gex_bias_label,
    select_material_strikes,
)
from expected_move_bot.gex_data import choose_overview_expirations


def test_contract_gex_is_dollars_for_one_percent_move() -> None:
    assert contract_gex(0.01, 100, 200.0, 100) == pytest.approx(40_000)


def test_aggregate_gex_uses_positive_calls_and_negative_puts() -> None:
    expiration = date(2026, 10, 16)
    contracts = [
        OptionGexInput(expiration, 200, True, 0.01, 100),
        OptionGexInput(expiration, 200, False, 0.02, 50),
        OptionGexInput(expiration, 210, True, 0.005, 40),
    ]

    expiry = aggregate_gex_by_expiry(contracts, 200)
    strikes = aggregate_gex_by_strike(contracts, 200)

    assert expiry[0].call_gex == pytest.approx(48_000)
    assert expiry[0].put_gex == pytest.approx(-40_000)
    assert strikes[0].strike == 200
    assert strikes[0].call_open_interest == 100
    assert strikes[0].put_open_interest == 50


def test_gex_bias_uses_net_divided_by_gross_exposure() -> None:
    snapshot = GexExpirySnapshot(
        symbol="TEST",
        description="Test",
        price=100,
        change=None,
        change_percent=None,
        as_of=datetime(2026, 9, 19),
        rows=[ExpiryGexRow(date(2026, 10, 16), 120_000_000, -20_000_000)],
        contracts_received=2,
        contracts_requested=2,
    )

    assert snapshot.total_gex == 100_000_000
    assert snapshot.gross_gex == 140_000_000
    assert snapshot.gex_bias == pytest.approx(100 / 140)
    assert gex_bias_label(snapshot.gex_bias) == "Strongly Positive"


@pytest.mark.parametrize(
    ("bias", "label"),
    [
        (0.04, "Balanced"),
        (-0.20, "Slightly Negative"),
        (0.45, "Moderately Positive"),
        (-0.75, "Strongly Negative"),
    ],
)
def test_gex_bias_labels(bias: float, label: str) -> None:
    assert gex_bias_label(bias) == label


def test_material_strike_filter_keeps_isolated_high_oi_after_empty_gap() -> None:
    rows = [
        StrikeGexRow(
            strike=float(strike),
            call_gex=1_000 if 90 <= strike <= 110 else 0,
            put_gex=-1_000 if 90 <= strike <= 110 else 0,
            call_open_interest=10 if 90 <= strike <= 110 else 0,
            put_open_interest=10 if 90 <= strike <= 110 else 0,
        )
        for strike in range(50, 301, 5)
    ]
    outlier_index = next(index for index, row in enumerate(rows) if row.strike == 250)
    rows[outlier_index] = StrikeGexRow(250, 250_000, -50_000, 8_000, 100)

    selected = select_material_strikes(rows, 100, core_count=15, top_count=8)

    assert any(row.strike == 250 for row in selected)
    assert selected[-1].strike == 255
    assert selected[-1].strike < 300


@dataclass
class FakeExpiration:
    expiration_date: date
    expiration_type: str
    days_to_expiration: int


@dataclass
class FakeChain:
    expirations: list[FakeExpiration]


def test_overview_expirations_keep_near_term_and_sample_long_monthlies() -> None:
    expirations = [
        FakeExpiration(
            date(2026 + index // 12, index % 12 + 1, 16),
            "Regular" if index % 2 else "Weekly",
            index * 7,
        )
        for index in range(60)
    ]

    selected = choose_overview_expirations([FakeChain(expirations)])  # type: ignore[arg-type]

    assert len(selected) <= 36
    assert [item.expiration_date for item in selected[:16]] == [
        item.expiration_date for item in expirations[:16]
    ]
    assert selected[-1].expiration_date == expirations[-1].expiration_date
