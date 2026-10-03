from datetime import date

from expected_move_bot.config import DEFAULT_GEX_HISTORY_SYMBOLS, Settings


def test_settings_parse_gex_history_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "discord")
    monkeypatch.setenv("TT_SECRET", "secret")
    monkeypatch.setenv("TT_REFRESH", "refresh")
    monkeypatch.setenv("TT_ACCOUNT_NUMBER", "5WX12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("GEX_HISTORY_SYMBOLS", "META, nvda, META")
    monkeypatch.setenv("GEX_HISTORY_EXPIRATIONS", "2026-12-18,2026-11-20")
    monkeypatch.setenv("GEX_HISTORY_CHANNEL_ID", "987654321")
    monkeypatch.setenv("EPR_CHANNEL_ID", "123456789")

    settings = Settings.from_environment()

    assert settings.database_url == "postgresql://example"
    assert settings.tt_account_number == "5WX12345"
    assert settings.gex_history_channel_id == 987654321
    assert settings.epr_channel_id == 123456789
    assert settings.gex_history_symbols == ("META", "NVDA")
    assert settings.gex_history_expirations == (
        date(2026, 11, 20),
        date(2026, 12, 18),
    )


def test_default_watchlist_matches_requested_symbols(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "discord")
    monkeypatch.setenv("TT_SECRET", "secret")
    monkeypatch.setenv("TT_REFRESH", "refresh")
    monkeypatch.delenv("GEX_HISTORY_SYMBOLS", raising=False)

    assert Settings.from_environment().gex_history_symbols == DEFAULT_GEX_HISTORY_SYMBOLS


def test_gex_history_channel_id_must_be_numeric(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "discord")
    monkeypatch.setenv("TT_SECRET", "secret")
    monkeypatch.setenv("TT_REFRESH", "refresh")
    monkeypatch.setenv("GEX_HISTORY_CHANNEL_ID", "not-a-number")

    try:
        Settings.from_environment()
    except RuntimeError as exc:
        assert str(exc) == "GEX_HISTORY_CHANNEL_ID must be a number"
    else:
        raise AssertionError("Expected invalid channel ID to fail")


def test_epr_channel_id_must_be_numeric(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "discord")
    monkeypatch.setenv("TT_SECRET", "secret")
    monkeypatch.setenv("TT_REFRESH", "refresh")
    monkeypatch.setenv("EPR_CHANNEL_ID", "not-a-number")

    try:
        Settings.from_environment()
    except RuntimeError as exc:
        assert str(exc) == "EPR_CHANNEL_ID must be a number"
    else:
        raise AssertionError("Expected invalid EPR channel ID to fail")
