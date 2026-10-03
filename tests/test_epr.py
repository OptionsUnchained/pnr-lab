from decimal import Decimal
from types import SimpleNamespace

import pytest

from expected_move_bot.epr import (
    epr_response_diagnostic,
    find_epr_entry,
    format_percent,
    margin_dry_run_payload,
    option_margin_dry_run_payload,
    percent_points,
    post_margin_dry_run,
    select_epr_probe_option,
    snapshot_from_entry,
)


class RecordingSession:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def _post(self, path: str, **kwargs: object) -> dict[str, object]:
        self.posts.append((path, kwargs))
        return {"new-order-results": {"groups": []}}


def test_find_epr_entry_in_dry_run_results() -> None:
    payload = {
        "new-order-results": {
            "groups": [
                {
                    "underlying-symbol": "QQQ",
                    "expected-price-range-down-percent": "0.15",
                    "expected-price-range-up-percent": "0.10",
                    "price-decrease-percent": "0.15",
                    "price-increase-percent": "0.10",
                }
            ]
        }
    }

    entry = find_epr_entry(payload, "qqq")

    assert entry is not None
    snapshot = snapshot_from_entry("QQQ", entry, "Pre-trade margin dry run")
    assert snapshot.down_percent == Decimal("15.00")
    assert snapshot.up_percent == Decimal("10.00")
    assert snapshot.stress_down_percent == Decimal("15.00")
    assert snapshot.stress_up_percent == Decimal("10.00")


def test_find_epr_entry_prefers_requested_symbol() -> None:
    payload = {
        "groups": [
            {
                "underlying-symbol": "SMH",
                "expected-price-range-down-percent": "17.5",
                "expected-price-range-up-percent": "13.25",
            },
            {
                "underlying-symbol": "QQQ",
                "expected-price-range-down-percent": "15",
                "expected-price-range-up-percent": "10",
            },
        ]
    }

    entry = find_epr_entry(payload, "QQQ")

    assert entry is not None
    assert entry["underlying-symbol"] == "QQQ"


def test_find_epr_entry_inherits_symbol_from_parent_margin_group() -> None:
    nested_epr = {
        "expected-price-range-down-percent": "0.15",
        "expected-price-range-up-percent": "0.10",
    }
    payload = {
        "new-order-results": {
            "groups": [
                {
                    "underlying-symbol": "QQQ",
                    "groups": [{"description": "LONG_UNDERLYING", **nested_epr}],
                },
                {
                    "underlying-symbol": "SMH",
                    "groups": [
                        {
                            "expected-price-range-down-percent": "0.18",
                            "expected-price-range-up-percent": "0.13",
                        }
                    ],
                },
            ]
        }
    }

    assert find_epr_entry(payload, "QQQ") == nested_epr | {"description": "LONG_UNDERLYING"}


def test_find_epr_entry_accepts_description_as_symbol_context() -> None:
    payload = {
        "new-order-results": {
            "groups": [
                {
                    "description": "BRK/B",
                    "groups": [
                        {
                            "expected-price-range-down-percent": "0.15",
                            "expected-price-range-up-percent": "0.10",
                        }
                    ],
                }
            ]
        }
    }

    assert find_epr_entry(payload, "BRK.B") is not None


def test_find_epr_entry_accepts_margin_group_code_as_symbol_context() -> None:
    target_epr = {
        "expected-price-range-down-percent": "0.35",
        "expected-price-range-up-percent": "0.25",
    }
    payload = {
        "new-order-results": {
            "groups": [
                {
                    "code": "AAPL",
                    "description": "Long equity position",
                    "groups": [target_epr],
                },
                {
                    "code": "NVDA",
                    "description": "Existing position",
                    "groups": [
                        {
                            "expected-price-range-down-percent": "0.40",
                            "expected-price-range-up-percent": "0.30",
                        }
                    ],
                },
            ]
        }
    }

    assert find_epr_entry(payload, "AAPL") == target_epr


def test_epr_response_diagnostic_excludes_margin_values() -> None:
    payload = {
        "new-order-results": {
            "groups": [
                {
                    "code": "AAPL",
                    "margin-requirement": "123456.78",
                    "groups": [
                        {
                            "expected-price-range-down-percent": "0.35",
                            "expected-price-range-up-percent": "0.25",
                        }
                    ],
                }
            ]
        }
    }

    diagnostic = epr_response_diagnostic(payload)

    assert "top-keys=['new-order-results']" in diagnostic
    assert "epr-candidates=1" in diagnostic
    assert "contexts=['AAPL']" in diagnostic
    assert "123456.78" not in diagnostic


def test_percent_formatting_accepts_fraction_or_points() -> None:
    assert percent_points("0.125") == Decimal("12.500")
    assert percent_points("12.5") == Decimal("12.5")
    assert percent_points("-0.15") == Decimal("15.00")
    assert format_percent(Decimal("12.5"), "-") == "-12.50%"


def test_equity_margin_payload_is_a_hypothetical_purchase() -> None:
    payload = margin_dry_run_payload("5WX12345", "AAPL")

    assert payload["legs"] == [
        {
            "symbol": "AAPL",
            "instrument-type": "Equity",
            "quantity": "1",
            "action": "Buy to Open",
        }
    ]


def test_option_margin_payload_is_a_hypothetical_short_option() -> None:
    payload = option_margin_dry_run_payload(
        "5WX12345",
        "AAPL",
        "AAPL  261120C00250000",
    )

    assert payload["underlying-symbol"] == "AAPL"
    assert payload["order-type"] == "Limit"
    assert payload["price"] == "0.05"
    assert payload["price-effect"] == "Credit"
    assert payload["legs"] == [
        {
            "symbol": "AAPL  261120C00250000",
            "instrument-type": "Equity Option",
            "quantity": "1",
            "remaining-quantity": "1",
            "action": "Sell to Open",
        }
    ]


def test_select_epr_probe_option_uses_middle_strike_near_45_dte() -> None:
    expiration = SimpleNamespace(
        days_to_expiration=43,
        expiration_date="2026-11-20",
        strikes=[
            SimpleNamespace(strike_price=Decimal("300"), call="CALL300"),
            SimpleNamespace(strike_price=Decimal("200"), call="CALL200"),
            SimpleNamespace(strike_price=Decimal("250"), call="CALL250"),
        ],
    )
    chain = SimpleNamespace(expirations=[expiration])

    assert select_epr_probe_option([chain]) == "CALL250"  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_epr_posts_only_to_margin_dry_run() -> None:
    session = RecordingSession()
    payload = {"underlying-symbol": "CAT"}

    await post_margin_dry_run(session, "5WX12345", payload)  # type: ignore[arg-type]

    assert session.posts == [
        (
            "/margin/accounts/5WX12345/dry-run",
            {"json": payload},
        )
    ]


@pytest.mark.asyncio
async def test_epr_rejects_account_number_path_injection() -> None:
    session = RecordingSession()

    try:
        await post_margin_dry_run(  # type: ignore[arg-type]
            session,
            "5WX12345/orders",
            {"underlying-symbol": "CAT"},
        )
    except ValueError as exc:
        assert str(exc) == "Tastytrade returned an invalid account number"
    else:
        raise AssertionError("Expected endpoint safety guard to reject the account number")

    assert session.posts == []
