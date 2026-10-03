from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import asyncpg

from expected_move_bot.gex import GexStrikeSnapshot, StrikeGexRow, gex_bias_label
from expected_move_bot.movers import PACIFIC


@dataclass(frozen=True)
class WallLevel:
    strike: float
    gex: float


@dataclass(frozen=True)
class GexHistoryPoint:
    snapshot_date: date
    captured_at: datetime
    symbol: str
    expiration_date: date
    expiration_dte: int
    spot_price: float
    total_call_gex: float
    total_put_gex: float
    net_gex: float
    gross_gex: float
    bias: float
    bias_label: str
    call_wall_strike: float | None
    second_call_wall_strike: float | None
    third_call_wall_strike: float | None
    put_wall_strike: float | None
    second_put_wall_strike: float | None
    third_put_wall_strike: float | None


@dataclass(frozen=True)
class GexCaptureStatus:
    symbol: str
    expiration_date: date
    saved: bool
    bias: float | None = None
    contracts_received: int = 0
    contracts_requested: int = 0
    error: str | None = None

    @property
    def complete(self) -> bool:
        return (
            self.saved
            and self.contracts_requested > 0
            and self.contracts_received == self.contracts_requested
        )


@dataclass(frozen=True)
class GexCaptureReport:
    captured_at: datetime
    statuses: tuple[GexCaptureStatus, ...]

    @property
    def saved_count(self) -> int:
        return sum(status.saved for status in self.statuses)

    @property
    def complete_count(self) -> int:
        return sum(status.complete for status in self.statuses)

    @property
    def expected_count(self) -> int:
        return len(self.statuses)


def format_gex_collection_section(
    report: GexCaptureReport,
    expiration_date: date,
) -> str:
    lines: list[str] = []
    for status in report.statuses:
        if status.expiration_date != expiration_date:
            continue
        if not status.saved:
            lines.append(f"❌ **{status.symbol}** · failed")
            continue
        icon = "✅" if status.complete else "⚠️"
        bias = f"{status.bias:+.0%}" if status.bias is not None else "N/A"
        coverage = f"{status.contracts_received}/{status.contracts_requested} contracts"
        lines.append(f"{icon} **{status.symbol}** · {bias} · {coverage}")
    return "\n".join(lines) or "No tracked symbols"


def ranked_walls(
    rows: list[StrikeGexRow],
) -> tuple[list[WallLevel], list[WallLevel]]:
    calls = sorted(
        (WallLevel(row.strike, row.call_gex) for row in rows if row.call_gex > 0),
        key=lambda wall: (-wall.gex, wall.strike),
    )[:3]
    puts = sorted(
        (WallLevel(row.strike, row.put_gex) for row in rows if row.put_gex < 0),
        key=lambda wall: (wall.gex, wall.strike),
    )[:3]
    return calls, puts


def should_capture_gex_history(now: datetime, last_date: date | None) -> bool:
    return (
        now.weekday() < 5
        and now.hour == 6
        and 45 <= now.minute < 55
        and last_date != now.date()
    )


class GexHistoryStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=4,
            command_timeout=60,
        )
        await self._create_tables()

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _create_tables(self) -> None:
        if self.pool is None:
            raise RuntimeError("GEX history database is not connected")
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gex_daily_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    snapshot_date DATE NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    expiration_date DATE NOT NULL,
                    expiration_dte INTEGER NOT NULL,
                    spot_price DOUBLE PRECISION NOT NULL,
                    total_call_gex DOUBLE PRECISION NOT NULL,
                    total_put_gex DOUBLE PRECISION NOT NULL,
                    net_gex DOUBLE PRECISION NOT NULL,
                    gross_gex DOUBLE PRECISION NOT NULL,
                    bias DOUBLE PRECISION NOT NULL,
                    bias_label TEXT NOT NULL,
                    call_wall_strike DOUBLE PRECISION,
                    call_wall_gex DOUBLE PRECISION,
                    second_call_wall_strike DOUBLE PRECISION,
                    second_call_wall_gex DOUBLE PRECISION,
                    third_call_wall_strike DOUBLE PRECISION,
                    third_call_wall_gex DOUBLE PRECISION,
                    put_wall_strike DOUBLE PRECISION,
                    put_wall_gex DOUBLE PRECISION,
                    second_put_wall_strike DOUBLE PRECISION,
                    second_put_wall_gex DOUBLE PRECISION,
                    third_put_wall_strike DOUBLE PRECISION,
                    third_put_wall_gex DOUBLE PRECISION,
                    contracts_received INTEGER NOT NULL,
                    contracts_requested INTEGER NOT NULL,
                    UNIQUE (snapshot_date, symbol, expiration_date)
                );

                CREATE INDEX IF NOT EXISTS gex_daily_snapshots_lookup
                    ON gex_daily_snapshots
                    (symbol, expiration_date, snapshot_date DESC);

                CREATE TABLE IF NOT EXISTS gex_daily_strikes (
                    snapshot_id BIGINT NOT NULL REFERENCES gex_daily_snapshots(id)
                        ON DELETE CASCADE,
                    strike DOUBLE PRECISION NOT NULL,
                    call_gex DOUBLE PRECISION NOT NULL,
                    put_gex DOUBLE PRECISION NOT NULL,
                    call_open_interest BIGINT NOT NULL,
                    put_open_interest BIGINT NOT NULL,
                    PRIMARY KEY (snapshot_id, strike)
                );

                CREATE INDEX IF NOT EXISTS gex_daily_strikes_snapshot
                    ON gex_daily_strikes (snapshot_id, strike);
                """
            )

    async def save_snapshot(self, snapshot: GexStrikeSnapshot) -> int:
        if self.pool is None:
            raise RuntimeError("GEX history database is not connected")
        calls, puts = ranked_walls(snapshot.rows)

        def value(levels: list[WallLevel], index: int, field: str) -> float | None:
            if index >= len(levels):
                return None
            return getattr(levels[index], field)

        total_call_gex = sum(row.call_gex for row in snapshot.rows)
        total_put_gex = sum(row.put_gex for row in snapshot.rows)
        snapshot_date = snapshot.as_of.astimezone(PACIFIC).date()
        expiration_dte = (snapshot.expiration_date - snapshot_date).days
        async with self.pool.acquire() as connection, connection.transaction():
            snapshot_id = await connection.fetchval(
                """
                    INSERT INTO gex_daily_snapshots (
                        snapshot_date, captured_at, symbol, expiration_date,
                        expiration_dte, spot_price, total_call_gex, total_put_gex,
                        net_gex, gross_gex, bias, bias_label,
                        call_wall_strike, call_wall_gex,
                        second_call_wall_strike, second_call_wall_gex,
                        third_call_wall_strike, third_call_wall_gex,
                        put_wall_strike, put_wall_gex,
                        second_put_wall_strike, second_put_wall_gex,
                        third_put_wall_strike, third_put_wall_gex,
                        contracts_received, contracts_requested
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
                        $23, $24, $25, $26
                    )
                    ON CONFLICT (snapshot_date, symbol, expiration_date)
                    DO UPDATE SET
                        captured_at = EXCLUDED.captured_at,
                        expiration_dte = EXCLUDED.expiration_dte,
                        spot_price = EXCLUDED.spot_price,
                        total_call_gex = EXCLUDED.total_call_gex,
                        total_put_gex = EXCLUDED.total_put_gex,
                        net_gex = EXCLUDED.net_gex,
                        gross_gex = EXCLUDED.gross_gex,
                        bias = EXCLUDED.bias,
                        bias_label = EXCLUDED.bias_label,
                        call_wall_strike = EXCLUDED.call_wall_strike,
                        call_wall_gex = EXCLUDED.call_wall_gex,
                        second_call_wall_strike = EXCLUDED.second_call_wall_strike,
                        second_call_wall_gex = EXCLUDED.second_call_wall_gex,
                        third_call_wall_strike = EXCLUDED.third_call_wall_strike,
                        third_call_wall_gex = EXCLUDED.third_call_wall_gex,
                        put_wall_strike = EXCLUDED.put_wall_strike,
                        put_wall_gex = EXCLUDED.put_wall_gex,
                        second_put_wall_strike = EXCLUDED.second_put_wall_strike,
                        second_put_wall_gex = EXCLUDED.second_put_wall_gex,
                        third_put_wall_strike = EXCLUDED.third_put_wall_strike,
                        third_put_wall_gex = EXCLUDED.third_put_wall_gex,
                        contracts_received = EXCLUDED.contracts_received,
                        contracts_requested = EXCLUDED.contracts_requested
                    RETURNING id
                    """,
                snapshot_date,
                snapshot.as_of,
                snapshot.symbol,
                snapshot.expiration_date,
                expiration_dte,
                snapshot.price,
                total_call_gex,
                total_put_gex,
                snapshot.total_gex,
                snapshot.gross_gex,
                snapshot.gex_bias,
                gex_bias_label(snapshot.gex_bias),
                value(calls, 0, "strike"),
                value(calls, 0, "gex"),
                value(calls, 1, "strike"),
                value(calls, 1, "gex"),
                value(calls, 2, "strike"),
                value(calls, 2, "gex"),
                value(puts, 0, "strike"),
                value(puts, 0, "gex"),
                value(puts, 1, "strike"),
                value(puts, 1, "gex"),
                value(puts, 2, "strike"),
                value(puts, 2, "gex"),
                snapshot.contracts_received,
                snapshot.contracts_requested,
            )
            await connection.execute(
                "DELETE FROM gex_daily_strikes WHERE snapshot_id = $1",
                snapshot_id,
            )
            await connection.executemany(
                """
                    INSERT INTO gex_daily_strikes (
                        snapshot_id, strike, call_gex, put_gex,
                        call_open_interest, put_open_interest
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                [
                    (
                        snapshot_id,
                        row.strike,
                        row.call_gex,
                        row.put_gex,
                        row.call_open_interest,
                        row.put_open_interest,
                    )
                    for row in snapshot.rows
                ],
            )
        return int(snapshot_id)

    async def save_snapshot_if_absent(self, snapshot: GexStrikeSnapshot) -> int:
        """Seed a day from a manual command without replacing its scheduled capture."""
        if self.pool is None:
            raise RuntimeError("GEX history database is not connected")
        snapshot_date = snapshot.as_of.astimezone(PACIFIC).date()
        existing_id = await self.pool.fetchval(
            """
            SELECT id
            FROM gex_daily_snapshots
            WHERE snapshot_date = $1 AND symbol = $2 AND expiration_date = $3
            """,
            snapshot_date,
            snapshot.symbol,
            snapshot.expiration_date,
        )
        if existing_id is not None:
            return int(existing_id)
        return await self.save_snapshot(snapshot)

    async def fetch_history(
        self,
        symbol: str,
        expiration_date: date,
        days: int = 30,
    ) -> list[GexHistoryPoint]:
        if self.pool is None:
            raise RuntimeError("GEX history database is not connected")
        start_date = datetime.now(PACIFIC).date() - timedelta(days=max(1, days) - 1)
        rows = await self.pool.fetch(
            """
            SELECT
                snapshot_date, captured_at, symbol, expiration_date,
                expiration_dte, spot_price, total_call_gex, total_put_gex,
                net_gex, gross_gex, bias, bias_label,
                call_wall_strike, second_call_wall_strike, third_call_wall_strike,
                put_wall_strike, second_put_wall_strike, third_put_wall_strike
            FROM gex_daily_snapshots
            WHERE symbol = $1
              AND expiration_date = $2
              AND snapshot_date >= $3
            ORDER BY snapshot_date ASC
            """,
            symbol.upper(),
            expiration_date,
            start_date,
        )
        return [GexHistoryPoint(**dict(row)) for row in rows]


def format_gex_history_table(points: list[GexHistoryPoint]) -> str:
    lines = [
        f"{'Date':<5} {'Price':>8} {'Bias':>6} {'PutW':>7} {'CallW':>7} {'Call2':>7}",
        f"{'-' * 5} {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 7} {'-' * 7}",
    ]
    for point in points:
        lines.append(
            f"{point.snapshot_date:%m/%d} "
            f"{point.spot_price:>8.2f} "
            f"{point.bias:>+6.0%} "
            f"{format_wall(point.put_wall_strike):>7} "
            f"{format_wall(point.call_wall_strike):>7} "
            f"{format_wall(point.second_call_wall_strike):>7}"
        )
    return f"```\n{'\n'.join(lines)}\n```"


def format_wall(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
