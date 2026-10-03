from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from expected_move_bot.market_data import (
    TastytradeMarketData,
    collect_latest_candle_prices,
    extended_session_bounds,
    extended_trade_prices,
    extract_market_caps,
)
from expected_move_bot.movers import MoversMode


def test_extract_market_caps_ignores_malformed_nested_expiration_data() -> None:
    items = [
        {
            "symbol": "GOOD",
            "market-cap": "25000000000",
            "option-expiration-implied-volatilities": [
                {
                    "expiration-date": "2019-01-18",
                    "implied-volatility": "1.896938",
                    # Tastytrade sometimes omits settlement-type here.
                }
            ],
        },
        {"symbol": "SMALL", "market-cap": "19000000000"},
        {"symbol": "MISSING"},
    ]

    assert extract_market_caps(items, 20_000_000_000) == {"GOOD": 25_000_000_000}


def test_extended_session_uses_correct_reference_close() -> None:
    universe = {"AAA": ("AAA", 25_000_000_000)}
    prices = {"AAA": 110.0}
    summaries = {
        "AAA": SimpleNamespace(prev_day_close_price=100, day_close_price=105)
    }

    premarket = TastytradeMarketData._extended_session_movers(
        universe, prices, summaries, MoversMode.PREMARKET
    )[0]
    after_market = TastytradeMarketData._extended_session_movers(
        universe, prices, summaries, MoversMode.AFTER_MARKET
    )[0]

    assert premarket.price == 110
    assert premarket.change_percent == pytest.approx(0.10)
    assert after_market.change_percent == pytest.approx(5 / 105)


def test_extended_session_bounds_use_pacific_market_hours() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    pre_start, pre_end = extended_session_bounds(
        datetime(2026, 9, 21, 6, 15, tzinfo=pacific), MoversMode.PREMARKET
    )
    after_start, after_end = extended_session_bounds(
        datetime(2026, 9, 21, 13, 30, tzinfo=pacific), MoversMode.AFTER_MARKET
    )

    assert (pre_start.hour, pre_start.minute) == (1, 0)
    assert (pre_end.hour, pre_end.minute) == (6, 15)
    assert (after_start.hour, after_start.minute) == (13, 0)
    assert (after_end.hour, after_end.minute) == (13, 30)


def test_extended_trade_prices_only_keeps_trades_inside_selected_session() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 9, 21, 13, 0, tzinfo=pacific)
    end = datetime(2026, 9, 21, 13, 30, tzinfo=pacific)
    trades = {
        "GOOD": SimpleNamespace(
            extended_trading_hours=True,
            time=round(datetime(2026, 9, 21, 13, 12, tzinfo=pacific).timestamp() * 1000),
            price=101.25,
        ),
        "REGULAR": SimpleNamespace(
            extended_trading_hours=False,
            time=round(datetime(2026, 9, 21, 13, 12, tzinfo=pacific).timestamp() * 1000),
            price=102,
        ),
        "STALE": SimpleNamespace(
            extended_trading_hours=True,
            time=round(datetime(2026, 9, 21, 12, 59, tzinfo=pacific).timestamp() * 1000),
            price=103,
        ),
    }

    assert extended_trade_prices(trades, start, end) == {"GOOD": 101.25}


@pytest.mark.asyncio
async def test_extended_session_uses_latest_nonempty_candle_close() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 9, 21, 13, 0, tzinfo=pacific)
    end = datetime(2026, 9, 21, 13, 30, tzinfo=pacific)

    class FakeStreamer:
        async def listen(self, _event_type):
            for candle in [
                SimpleNamespace(
                    event_symbol="AAA{=5m}",
                    count=10,
                    time=round(start.timestamp() * 1000),
                    close=101,
                ),
                SimpleNamespace(
                    event_symbol="AAA{=5m}",
                    count=0,
                    time=round((start.timestamp() + 300) * 1000),
                    close=999,
                ),
                SimpleNamespace(
                    event_symbol="AAA{=5m}",
                    count=4,
                    time=round((start.timestamp() + 600) * 1000),
                    close=103,
                ),
            ]:
                yield candle

    prices = await collect_latest_candle_prices(
        FakeStreamer(), {"AAA"}, start, end, timeout=1
    )

    assert prices == {"AAA": 103.0}
