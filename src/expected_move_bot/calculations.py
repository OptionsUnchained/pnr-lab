from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class ExpirationLike(Protocol):
    expiration_type: str
    expiration_date: date
    days_to_expiration: int


@dataclass(frozen=True)
class ExpectedMoveRow:
    expiration_date: date
    dte: int
    high: float
    low: float
    move: float


def chain_expected_move(
    atm_call: float,
    atm_put: float,
    first_otm_call: float,
    first_otm_put: float,
    second_otm_call: float,
    second_otm_put: float,
) -> float:
    """Calculate Tastytrade's platform expected move from option marks."""
    midpoints = (
        atm_call,
        atm_put,
        first_otm_call,
        first_otm_put,
        second_otm_call,
        second_otm_put,
    )
    if any(midpoint < 0 for midpoint in midpoints):
        raise ValueError("option midpoints cannot be negative")
    atm_straddle = atm_call + atm_put
    first_otm_strangle = first_otm_call + first_otm_put
    second_otm_strangle = second_otm_call + second_otm_put
    return 0.6 * atm_straddle + 0.3 * first_otm_strangle + 0.1 * second_otm_strangle


def choose_regular_expirations(
    expirations: Iterable[ExpirationLike], limit: int = 5
) -> list[ExpirationLike]:
    """Pick the earliest distinct future regular monthly expirations."""
    if limit < 1:
        raise ValueError("limit must be positive")

    regular = sorted(
        (
            expiration
            for expiration in expirations
            if expiration.expiration_type.lower() == "regular"
            and expiration.days_to_expiration >= 0
        ),
        key=lambda item: (item.days_to_expiration, item.expiration_date),
    )
    if not regular:
        raise ValueError("No regular future expirations were returned")

    chosen: list[ExpirationLike] = []
    used_dates: set[date] = set()
    for expiration in regular:
        if expiration.expiration_date in used_dates:
            continue
        chosen.append(expiration)
        used_dates.add(expiration.expiration_date)
        if len(chosen) == limit:
            break
    return chosen


def build_expected_move_rows(
    price: float,
    expiration_quotes: Iterable[
        tuple[ExpirationLike, float, float, float, float, float, float]
    ],
) -> list[ExpectedMoveRow]:
    if price <= 0:
        raise ValueError("price must be positive")

    rows = []
    for expiration, *midpoints in expiration_quotes:
        move = chain_expected_move(*midpoints)
        rows.append(
            ExpectedMoveRow(
                expiration_date=expiration.expiration_date,
                dte=expiration.days_to_expiration,
                high=price + move,
                low=max(0.0, price - move),
                move=move,
            )
        )
    return rows


def iv_label(iv: float) -> tuple[str, str, int]:
    """Return label, emoji, and Discord embed color for decimal IV."""
    if iv < 0.20:
        return "Low", "🧊", 0x3498DB
    if iv < 0.35:
        return "Moderate", "🟢", 0x2ECC71
    if iv < 0.50:
        return "High", "🌶️", 0xF39C12
    return "Very High", "🔥", 0xE74C3C


def format_table(rows: Iterable[ExpectedMoveRow], price: float) -> str:
    if price <= 0:
        raise ValueError("price must be positive")
    sections = []
    for row in rows:
        expiration = row.expiration_date.strftime("%b %d")
        move_percent = row.move / price
        sections.append(
            f"**{expiration} · {row.dte} DTE**\n"
            f"`${row.low:,.2f} – ${row.high:,.2f} | "
            f"±${row.move:,.2f} ({move_percent:.1%})`"
        )
    return "\n\n".join(sections)
