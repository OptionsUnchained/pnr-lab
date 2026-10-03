from dataclasses import dataclass
from datetime import date

import pytest

from expected_move_bot.calculations import (
    build_expected_move_rows,
    chain_expected_move,
    choose_regular_expirations,
    format_table,
    iv_label,
)
from expected_move_bot.market_data import normalize_iv, normalize_symbol


@dataclass
class Expiration:
    expiration_type: str
    expiration_date: date
    days_to_expiration: int


def test_chain_expected_move_matches_tastytrade_style() -> None:
    move = chain_expected_move(7.625, 7.45, 5.35, 5.30, 3.625, 3.65)
    assert move == pytest.approx(12.9675)


def test_selects_earliest_five_distinct_regular_monthlies() -> None:
    expirations = [
        Expiration("Weekly", date(2026, 9, 25), 8),
        Expiration("Regular", date(2026, 9, 18), 1),
        Expiration("Regular", date(2026, 10, 16), 29),
        Expiration("Regular", date(2026, 11, 20), 64),
        Expiration("Regular", date(2026, 11, 20), 64),
        Expiration("Regular", date(2026, 12, 18), 92),
        Expiration("Regular", date(2027, 1, 15), 120),
        Expiration("Regular", date(2027, 2, 19), 155),
    ]
    selected = choose_regular_expirations(expirations)
    assert [item.days_to_expiration for item in selected] == [1, 29, 64, 92, 120]


def test_rows_and_table() -> None:
    expirations = [Expiration("Regular", date(2026, 10, 16), 30)]
    rows = build_expected_move_rows(
        219.40,
        [(expirations[0], 7.625, 7.45, 5.35, 5.30, 3.625, 3.65)],
    )
    table = format_table(rows, 219.40)
    assert "**Oct 16 · 30 DTE**" in table
    assert "`$206.43 – $232.37 | ±$12.97 (5.9%)`" in table


@pytest.mark.parametrize(
    ("iv", "label"),
    [(0.10, "Low"), (0.25, "Moderate"), (0.40, "High"), (0.578, "Very High")],
)
def test_iv_labels(iv: float, label: str) -> None:
    assert iv_label(iv)[0] == label


def test_symbol_normalization() -> None:
    assert normalize_symbol(" $crwd ") == "CRWD"
    with pytest.raises(ValueError):
        normalize_symbol("CRWD;DROP")


def test_iv_unit_normalization() -> None:
    assert normalize_iv(0.352, percentage_points=False) == pytest.approx(0.352)
    assert normalize_iv(35.2, percentage_points=True) == pytest.approx(0.352)
