from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from tastytrade import Account, Session
from tastytrade.instruments import Equity, NestedOptionChain

from expected_move_bot.market_data import normalize_symbol

MARGIN_DRY_RUN_PREFIX = "/margin/accounts/"
MARGIN_DRY_RUN_SUFFIX = "/dry-run"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EprSnapshot:
    symbol: str
    down_percent: Decimal
    up_percent: Decimal
    stress_down_percent: Decimal | None = None
    stress_up_percent: Decimal | None = None
    source: str = "Pre-trade margin dry run"


@dataclass(frozen=True)
class EprFetchResult:
    requested_symbol: str
    snapshot: EprSnapshot | None = None
    error: str | None = None


class TastytradeEprData:
    """Retrieve tastytrade's account-scoped EPR without placing an order."""

    def __init__(
        self,
        provider_secret: str,
        refresh_token: str,
        account_number: str | None = None,
    ) -> None:
        self.provider_secret = provider_secret
        self.refresh_token = refresh_token
        self.account_number = account_number

    async def snapshot(self, raw_symbol: str) -> EprSnapshot:
        symbol = normalize_symbol(raw_symbol)
        async with Session(self.provider_secret, self.refresh_token) as session:
            equity = await Equity.get(session, symbol)
            account = await self._resolve_account(session)
            report = await account.get_margin_requirements(session)
            return await self._snapshot_for_equity(
                session,
                account,
                equity,
                report.model_dump(by_alias=True),
            )

    async def snapshots(self, raw_symbols: tuple[str, ...]) -> tuple[EprFetchResult, ...]:
        """Retrieve many EPR values with one session, account lookup, and margin report."""
        symbols = tuple(dict.fromkeys(normalize_symbol(value) for value in raw_symbols))
        async with Session(self.provider_secret, self.refresh_token) as session:
            equities = await Equity.get(session, symbols)
            if not isinstance(equities, list):
                equities = [equities]
            equities_by_symbol = {equity.symbol: equity for equity in equities}
            account = await self._resolve_account(session)
            report = await account.get_margin_requirements(session)
            report_payload = report.model_dump(by_alias=True)

            results: list[EprFetchResult] = []
            for symbol in symbols:
                equity = equities_by_symbol.get(symbol)
                if equity is None:
                    LOGGER.warning(
                        "EPR unavailable for %s: equity lookup returned no result",
                        symbol,
                    )
                    results.append(
                        EprFetchResult(
                            requested_symbol=symbol,
                            error="Ticker is not available as a Tastytrade equity",
                        )
                    )
                    continue
                try:
                    snapshot = await self._snapshot_for_equity(
                        session,
                        account,
                        equity,
                        report_payload,
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "EPR unavailable for %s: %s: %s",
                        symbol,
                        type(exc).__name__,
                        exc,
                    )
                    results.append(
                        EprFetchResult(
                            requested_symbol=symbol,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                else:
                    results.append(EprFetchResult(symbol, snapshot=snapshot))
            return tuple(results)

    async def _snapshot_for_equity(
        self,
        session: Session,
        account: Account,
        equity: Equity,
        current_report: dict[str, Any],
    ) -> EprSnapshot:
        symbol = equity.symbol
        current = find_epr_entry(current_report, symbol)
        if current is not None:
            return snapshot_from_entry(symbol, current, "Current capital requirements")

        payload = margin_dry_run_payload(account.account_number, symbol)
        data = await post_margin_dry_run(session, account.account_number, payload)
        entry = find_epr_entry(data, symbol)
        if entry is None:
            LOGGER.info(
                "EPR equity dry run returned no margin group for %s; "
                "retrying with a hypothetical equity-option position",
                symbol,
            )
            chains = await NestedOptionChain.get(session, symbol)
            option_symbol = select_epr_probe_option(chains)
            fallback_payload = option_margin_dry_run_payload(
                account.account_number, symbol, option_symbol
            )
            data = await post_margin_dry_run(
                session,
                account.account_number,
                fallback_payload,
            )
            entry = find_epr_entry(data, symbol)
        if entry is None:
            LOGGER.warning(
                "EPR dry-run response shape for %s: %s",
                symbol,
                epr_response_diagnostic(data),
            )
            raise LookupError(
                f"Tastytrade completed the dry run but did not return EPR for {symbol}. "
                "Confirm that the selected account has portfolio margin and that the "
                "OAuth grant includes account/margin access."
            )
        return snapshot_from_entry(symbol, entry, "Pre-trade margin dry run")

    async def _resolve_account(self, session: Session) -> Account:
        if self.account_number:
            account = await Account.get(session, self.account_number)
            if isinstance(account, list):
                raise RuntimeError("Tastytrade returned an unexpected account list")
            return account

        accounts = await Account.get(session)
        if not isinstance(accounts, list):
            return accounts
        if len(accounts) == 1:
            return accounts[0]
        raise ValueError(
            "More than one tastytrade account is connected. Set TT_ACCOUNT_NUMBER in "
            "Railway to the portfolio-margin account the EPR command should use."
        )


async def post_margin_dry_run(
    session: Session,
    account_number: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST only to the margin simulator; this function cannot target order routes."""
    if not account_number.isalnum():
        raise ValueError("Tastytrade returned an invalid account number")

    path = f"{MARGIN_DRY_RUN_PREFIX}{account_number}{MARGIN_DRY_RUN_SUFFIX}"
    if not (
        path.startswith(MARGIN_DRY_RUN_PREFIX)
        and path.endswith(MARGIN_DRY_RUN_SUFFIX)
        and "/orders" not in path
    ):
        raise RuntimeError("EPR safety guard blocked a non-dry-run endpoint")

    return await session._post(path, json=payload)  # noqa: SLF001 - no public SDK wrapper


def margin_dry_run_payload(
    account_number: str,
    symbol: str,
) -> dict[str, Any]:
    return {
        "account-number": account_number,
        "underlying-symbol": symbol,
        "underlying-instrument-type": "Equity",
        "order-type": "Market",
        "time-in-force": "Day",
        "legs": [
            {
                "symbol": symbol,
                "instrument-type": "Equity",
                "quantity": "1",
                "action": "Buy to Open",
            }
        ],
    }


def option_margin_dry_run_payload(
    account_number: str,
    symbol: str,
    option_symbol: str,
) -> dict[str, Any]:
    return {
        "account-number": account_number,
        "underlying-symbol": symbol,
        "underlying-instrument-type": "Equity",
        "order-type": "Limit",
        "time-in-force": "Day",
        "price": "0.05",
        "price-effect": "Credit",
        "legs": [
            {
                "symbol": option_symbol,
                "instrument-type": "Equity Option",
                "quantity": "1",
                "remaining-quantity": "1",
                "action": "Sell to Open",
            }
        ],
    }


def select_epr_probe_option(chains: list[NestedOptionChain]) -> str:
    expirations = [
        expiration
        for chain in chains
        for expiration in chain.expirations
        if expiration.strikes and expiration.days_to_expiration >= 7
    ]
    if not expirations:
        raise LookupError("Tastytrade returned no usable option expiration for EPR")
    expiration = min(
        expirations,
        key=lambda item: (abs(item.days_to_expiration - 45), item.expiration_date),
    )
    strikes = sorted(expiration.strikes, key=lambda item: item.strike_price)
    option_symbol = strikes[len(strikes) // 2].call
    if not option_symbol:
        raise LookupError("Tastytrade returned no usable option contract for EPR")
    return option_symbol


def find_epr_entry(payload: Any, symbol: str) -> dict[str, Any] | None:
    """Find EPR fields, inheriting a ticker from enclosing margin groups."""
    target = normalize_match_symbol(symbol)

    def search(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        matched: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []

        def visit(child_value: Any, inherited_symbols: frozenset[str]) -> None:
            if isinstance(child_value, dict):
                local_symbols = {
                    normalized
                    for key in (
                        "underlying-symbol",
                        "symbol",
                        "root-symbol",
                        "code",
                        "description",
                    )
                    if (normalized := normalize_match_symbol(child_value.get(key)))
                }
                context_symbols = inherited_symbols | local_symbols
                if (
                    child_value.get("expected-price-range-up-percent") is not None
                    and child_value.get("expected-price-range-down-percent") is not None
                ):
                    candidates.append(child_value)
                    if target in context_symbols:
                        matched.append(child_value)
                for nested in child_value.values():
                    visit(nested, context_symbols)
            elif isinstance(child_value, list):
                for nested in child_value:
                    visit(nested, inherited_symbols)

        visit(value, frozenset())
        return matched, candidates

    if isinstance(payload, dict) and "new-order-results" in payload:
        matched, candidates = search(payload["new-order-results"])
        if matched:
            return matched[0]
        if len(candidates) == 1:
            return candidates[0]

    matched, candidates = search(payload)
    if matched:
        return matched[0]
    return candidates[0] if len(candidates) == 1 else None


def normalize_match_symbol(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().upper().removeprefix("$").replace(".", "/")
    if not candidate or len(candidate) > 12 or " " in candidate:
        return ""
    return candidate


def epr_response_diagnostic(payload: Any) -> str:
    """Describe EPR response structure without logging account or margin values."""
    epr_keys = {
        "expected-price-range-up-percent",
        "expected-price-range-down-percent",
    }
    identity_keys = ("underlying-symbol", "symbol", "root-symbol", "code")
    candidate_contexts: list[str] = []
    related_keys: set[str] = set()
    dict_count = 0

    def visit(value: Any, inherited: frozenset[str]) -> None:
        nonlocal dict_count
        if isinstance(value, dict):
            dict_count += 1
            local = {
                normalized
                for key in identity_keys
                if (normalized := normalize_match_symbol(value.get(key)))
            }
            context = inherited | local
            for key in value:
                lowered = str(key).lower()
                if "expected" in lowered or "price-range" in lowered:
                    related_keys.add(str(key))
            if epr_keys <= value.keys() and len(candidate_contexts) < 12:
                candidate_contexts.append("/".join(sorted(context)) or "<no-id>")
            for child in value.values():
                visit(child, context)
        elif isinstance(value, list):
            for child in value:
                visit(child, inherited)

    visit(payload, frozenset())
    top_keys = sorted(str(key) for key in payload) if isinstance(payload, dict) else []
    return (
        f"top-keys={top_keys}; dicts={dict_count}; "
        f"epr-candidates={len(candidate_contexts)}; contexts={candidate_contexts}; "
        f"related-keys={sorted(related_keys)}"
    )


def snapshot_from_entry(symbol: str, entry: dict[str, Any], source: str) -> EprSnapshot:
    return EprSnapshot(
        symbol=symbol,
        down_percent=percent_points(entry["expected-price-range-down-percent"]),
        up_percent=percent_points(entry["expected-price-range-up-percent"]),
        stress_down_percent=optional_percent_points(entry.get("price-decrease-percent")),
        stress_up_percent=optional_percent_points(entry.get("price-increase-percent")),
        source=source,
    )


def percent_points(value: Any) -> Decimal:
    """Normalize API percentages whether returned as 0.15 or 15."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LookupError(f"Tastytrade returned an invalid EPR percentage: {value!r}") from exc
    if abs(result) <= 1:
        result *= 100
    return abs(result)


def optional_percent_points(value: Any) -> Decimal | None:
    return None if value is None else percent_points(value)


def format_percent(value: Decimal, sign: str) -> str:
    return f"{sign}{value:.2f}%"
