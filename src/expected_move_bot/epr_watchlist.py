from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import asyncpg

from expected_move_bot.earnings import TRACKED_EARNINGS_SYMBOLS
from expected_move_bot.epr import EprFetchResult, EprSnapshot
from expected_move_bot.movers import PACIFIC

EPR_WATCHLIST_SYMBOLS = tuple(
    sorted((*TRACKED_EARNINGS_SYMBOLS, "SPY", "QQQ", "SMH"))
)
WHOLE_PERCENT = Decimal("1")


def round_percent(value: Decimal) -> Decimal:
    return value.quantize(WHOLE_PERCENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class EprHistoryPoint:
    snapshot_date: date
    symbol: str
    down_percent: Decimal
    up_percent: Decimal


@dataclass(frozen=True)
class EprWatchlistRow:
    symbol: str
    snapshot: EprSnapshot | None = None
    previous: EprHistoryPoint | None = None
    error: str | None = None

    @property
    def down_change(self) -> Decimal | None:
        if self.snapshot is None or self.previous is None:
            return None
        return round_percent(self.snapshot.down_percent) - round_percent(
            self.previous.down_percent
        )

    @property
    def up_change(self) -> Decimal | None:
        if self.snapshot is None or self.previous is None:
            return None
        return round_percent(self.snapshot.up_percent) - round_percent(
            self.previous.up_percent
        )

    @property
    def changed(self) -> bool:
        return (
            self.down_change is not None
            and self.up_change is not None
            and (self.down_change != 0 or self.up_change != 0)
        )


@dataclass(frozen=True)
class EprWatchlistReport:
    captured_at: datetime
    rows: tuple[EprWatchlistRow, ...]

    @property
    def successful_count(self) -> int:
        return sum(row.snapshot is not None for row in self.rows)

    @property
    def changed_count(self) -> int:
        return sum(row.changed for row in self.rows)

    @property
    def failure_count(self) -> int:
        return sum(row.snapshot is None for row in self.rows)


def build_epr_watchlist_report(
    display_symbols: tuple[str, ...],
    results: tuple[EprFetchResult, ...],
    previous: dict[str, EprHistoryPoint],
    captured_at: datetime,
) -> EprWatchlistReport:
    if len(display_symbols) != len(results):
        raise ValueError("EPR result count does not match the watchlist")
    rows = tuple(
        EprWatchlistRow(
            symbol=display_symbol,
            snapshot=result.snapshot,
            previous=previous.get(display_symbol),
            error=result.error,
        )
        for display_symbol, result in zip(display_symbols, results, strict=True)
    )
    return EprWatchlistReport(captured_at=captured_at, rows=rows)


def should_capture_epr_watchlist(now: datetime, last_date: date | None) -> bool:
    local = now.astimezone(PACIFIC)
    return (
        local.weekday() < 5
        and local.hour == 6
        and 31 <= local.minute < 41
        and last_date != local.date()
    )


def format_epr_watchlist(report: EprWatchlistReport) -> str:
    successful = [row for row in report.rows if row.snapshot is not None]
    changed = [row for row in successful if row.changed]
    prior_dates = sorted(
        {row.previous.snapshot_date for row in successful if row.previous is not None}
    )

    if prior_dates:
        comparison = (
            "Compared with each ticker's latest prior value "
            f"(latest date {prior_dates[-1]:%b %d})"
        )
        if changed:
            change_lines = "\n".join(
                f"**{row.symbol}** · Down {format_change(row.down_change)} pp · "
                f"Up {format_change(row.up_change)} pp"
                for row in changed
            )
            summary = f"**Changes ({len(changed)}):**\n{change_lines}"
        else:
            summary = "**Changes:** None"
    else:
        comparison = "First saved collection; daily changes begin with the next report"
        summary = "**Changes:** No prior collection"

    lines = [
        "Ticker   Down     Up",
        "------ ------ ------",
    ]
    for row in successful:
        snapshot = row.snapshot
        if snapshot is None:
            continue
        lines.append(
            f"{row.symbol:<6} "
            f"{format_percent(-snapshot.down_percent):>6} "
            f"{format_percent(snapshot.up_percent):>6}"
        )

    failures = [row.symbol for row in report.rows if row.snapshot is None]
    failure_text = f"\n⚠️ **Unavailable:** {', '.join(failures)}" if failures else ""
    return (
        f"{summary}\n{comparison}.\n\n"
        f"```\n{'\n'.join(lines)}\n```{failure_text}"
    )


def format_change(value: Decimal | None) -> str:
    return "--" if value is None else f"{value:+.0f}"


def format_percent(value: Decimal) -> str:
    return f"{round_percent(value):+.0f}%"


class EprHistoryStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=2,
            command_timeout=60,
        )
        await self._create_table()

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _create_table(self) -> None:
        if self.pool is None:
            raise RuntimeError("EPR history database is not connected")
        await self.pool.execute(
            """
            CREATE TABLE IF NOT EXISTS epr_daily_snapshots (
                snapshot_date DATE NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL,
                symbol TEXT NOT NULL,
                down_percent NUMERIC NOT NULL,
                up_percent NUMERIC NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (snapshot_date, symbol)
            );

            CREATE INDEX IF NOT EXISTS epr_daily_snapshots_lookup
                ON epr_daily_snapshots (symbol, snapshot_date DESC);
            """
        )

    async def fetch_previous(
        self,
        symbols: tuple[str, ...],
        before_date: date,
    ) -> dict[str, EprHistoryPoint]:
        if self.pool is None:
            raise RuntimeError("EPR history database is not connected")
        rows = await self.pool.fetch(
            """
            SELECT DISTINCT ON (symbol)
                snapshot_date, symbol, down_percent, up_percent
            FROM epr_daily_snapshots
            WHERE symbol = ANY($1::text[])
              AND snapshot_date < $2
            ORDER BY symbol, snapshot_date DESC
            """,
            list(symbols),
            before_date,
        )
        return {
            row["symbol"]: EprHistoryPoint(
                snapshot_date=row["snapshot_date"],
                symbol=row["symbol"],
                down_percent=row["down_percent"],
                up_percent=row["up_percent"],
            )
            for row in rows
        }

    async def save_report(self, report: EprWatchlistReport) -> None:
        if self.pool is None:
            raise RuntimeError("EPR history database is not connected")
        snapshot_date = report.captured_at.astimezone(PACIFIC).date()
        values = [
            (
                snapshot_date,
                report.captured_at,
                row.symbol,
                row.snapshot.down_percent,
                row.snapshot.up_percent,
                row.snapshot.source,
            )
            for row in report.rows
            if row.snapshot is not None
        ]
        if not values:
            return
        await self.pool.executemany(
            """
            INSERT INTO epr_daily_snapshots (
                snapshot_date, captured_at, symbol,
                down_percent, up_percent, source
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (snapshot_date, symbol)
            DO UPDATE SET
                captured_at = EXCLUDED.captured_at,
                down_percent = EXCLUDED.down_percent,
                up_percent = EXCLUDED.up_percent,
                source = EXCLUDED.source
            """,
            values,
        )
