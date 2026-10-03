from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image

from expected_move_bot.movers import MarketMover, MarketMoversSnapshot
from expected_move_bot.movers_image import GREEN, RED, WIDTH, render_market_movers


def test_market_movers_image_is_valid_png_with_change_colors() -> None:
    snapshot = MarketMoversSnapshot(
        as_of=datetime(2026, 9, 18, 6, 10, tzinfo=ZoneInfo("America/Los_Angeles")),
        gainers=[MarketMover("NVDA", 225.67, 6.27, 0.0286, 5_480_000_000_000)],
        losers=[MarketMover("CMG", 39.18, -2.82, -0.0672, 52_600_000_000)],
        eligible_count=438,
        quoted_count=412,
    )
    data = render_market_movers(snapshot, "Premarket")
    image = Image.open(BytesIO(data))
    colors = {color for _, color in image.getcolors(maxcolors=image.width * image.height) or []}

    assert image.format == "PNG"
    assert image.width == WIDTH
    assert image.height > 200
    assert tuple(bytes.fromhex(GREEN.removeprefix("#"))) in colors
    assert tuple(bytes.fromhex(RED.removeprefix("#"))) in colors
