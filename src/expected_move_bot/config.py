from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

DEFAULT_GEX_HISTORY_SYMBOLS = (
    "NVDA",
    "AVGO",
    "META",
    "AMZN",
    "GOOGL",
    "AAPL",
    "TSLA",
    "AMD",
)
DEFAULT_GEX_HISTORY_EXPIRATIONS = (date(2026, 11, 20), date(2026, 12, 18))


@dataclass(frozen=True)
class Settings:
    discord_token: str
    tt_secret: str
    tt_refresh: str
    tt_account_number: str | None = None
    discord_guild_id: int | None = None
    movers_channel_id: int | None = None
    gex_history_channel_id: int | None = None
    epr_channel_id: int | None = None
    command_cooldown_seconds: float = 5.0
    database_url: str | None = None
    gex_history_symbols: tuple[str, ...] = DEFAULT_GEX_HISTORY_SYMBOLS
    gex_history_expirations: tuple[date, ...] = DEFAULT_GEX_HISTORY_EXPIRATIONS

    @classmethod
    def from_environment(cls) -> Settings:
        required = ("DISCORD_TOKEN", "TT_SECRET", "TT_REFRESH")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        guild_text = os.getenv("DISCORD_GUILD_ID", "").strip()
        try:
            guild_id = int(guild_text) if guild_text else None
        except ValueError as exc:
            raise RuntimeError("DISCORD_GUILD_ID must be a number") from exc

        movers_channel_text = os.getenv("MOVERS_CHANNEL_ID", "").strip()
        try:
            movers_channel_id = int(movers_channel_text) if movers_channel_text else None
        except ValueError as exc:
            raise RuntimeError("MOVERS_CHANNEL_ID must be a number") from exc

        gex_history_channel_text = os.getenv("GEX_HISTORY_CHANNEL_ID", "").strip()
        try:
            gex_history_channel_id = (
                int(gex_history_channel_text) if gex_history_channel_text else None
            )
        except ValueError as exc:
            raise RuntimeError("GEX_HISTORY_CHANNEL_ID must be a number") from exc

        epr_channel_text = os.getenv("EPR_CHANNEL_ID", "").strip()
        try:
            epr_channel_id = int(epr_channel_text) if epr_channel_text else None
        except ValueError as exc:
            raise RuntimeError("EPR_CHANNEL_ID must be a number") from exc

        try:
            cooldown = float(os.getenv("COMMAND_COOLDOWN_SECONDS", "5"))
        except ValueError as exc:
            raise RuntimeError("COMMAND_COOLDOWN_SECONDS must be numeric") from exc

        symbols_text = os.getenv(
            "GEX_HISTORY_SYMBOLS",
            ",".join(DEFAULT_GEX_HISTORY_SYMBOLS),
        )
        symbols = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols_text.split(",")
                if symbol.strip()
            )
        )
        if not symbols:
            raise RuntimeError("GEX_HISTORY_SYMBOLS must contain at least one ticker")

        expirations_text = os.getenv(
            "GEX_HISTORY_EXPIRATIONS",
            ",".join(value.isoformat() for value in DEFAULT_GEX_HISTORY_EXPIRATIONS),
        )
        try:
            expirations = tuple(
                sorted(
                    {
                        date.fromisoformat(value.strip())
                        for value in expirations_text.split(",")
                        if value.strip()
                    }
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "GEX_HISTORY_EXPIRATIONS must contain YYYY-MM-DD dates"
            ) from exc
        if not expirations:
            raise RuntimeError(
                "GEX_HISTORY_EXPIRATIONS must contain at least one expiration"
            )

        database_url = os.getenv("DATABASE_URL", "").strip() or None
        tt_account_number = os.getenv("TT_ACCOUNT_NUMBER", "").strip() or None

        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            tt_secret=os.environ["TT_SECRET"],
            tt_refresh=os.environ["TT_REFRESH"],
            tt_account_number=tt_account_number,
            discord_guild_id=guild_id,
            movers_channel_id=movers_channel_id,
            gex_history_channel_id=gex_history_channel_id,
            epr_channel_id=epr_channel_id,
            command_cooldown_seconds=max(0.0, cooldown),
            database_url=database_url,
            gex_history_symbols=symbols,
            gex_history_expirations=expirations,
        )
