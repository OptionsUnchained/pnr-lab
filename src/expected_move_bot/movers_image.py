from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from expected_move_bot.movers import (
    MarketMover,
    MarketMoversSnapshot,
    comparison_label,
    format_market_cap,
)

WIDTH = 720
BACKGROUND = "#2b2d31"
TEXT = "#f2f3f5"
MUTED = "#b5bac1"
GREEN = "#3ba55d"
RED = "#ed4245"
BLURPLE = "#5865f2"


def render_market_movers(snapshot: MarketMoversSnapshot, report_label: str) -> bytes:
    """Render the compact two-column movers table as a Discord-ready PNG."""
    row_count = max(len(snapshot.gainers), len(snapshot.losers), 1)
    height = 182 + row_count * 46 + 54
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(30, bold=True)
    header_font = load_font(23, bold=True)
    primary_font = load_font(21, bold=True)
    secondary_font = load_font(18, mono=True)
    small_font = load_font(15)

    draw.rounded_rectangle((0, 0, WIDTH - 1, height - 1), radius=18, outline="#3f4147")
    draw.rounded_rectangle((0, 0, 7, height - 1), radius=4, fill=BLURPLE)
    draw.text((28, 22), f"$20B+ MARKET MOVERS — {report_label.upper()}", TEXT, title_font)
    timestamp = (
        f"{snapshot.as_of:%a %b} {snapshot.as_of.day}, "
        f"{snapshot.as_of.strftime('%I:%M %p').lstrip('0')} PT"
    )
    draw.text((28, 62), timestamp, MUTED, small_font)

    left_x, right_x = 30, 390
    value_offset = 172
    draw.text((left_x, 98), "GAINERS", GREEN, header_font)
    draw.text((right_x, 98), "LOSERS", RED, header_font)
    draw.line((28, 132, WIDTH - 28, 132), fill="#45474d", width=1)

    for index in range(row_count):
        y = 145 + index * 46
        if index < len(snapshot.gainers):
            draw_mover(
                draw,
                snapshot.gainers[index],
                index + 1,
                left_x,
                left_x + value_offset,
                y,
                GREEN,
                primary_font,
                secondary_font,
            )
        if index < len(snapshot.losers):
            draw_mover(
                draw,
                snapshot.losers[index],
                index + 1,
                right_x,
                right_x + value_offset,
                y,
                RED,
                primary_font,
                secondary_font,
            )

    footer_y = 154 + row_count * 46
    footer = (
        f"{comparison_label(snapshot.mode)}  •  Market cap ≥ $20B  •  "
        f"{snapshot.quoted_count}/{snapshot.eligible_count} usable prices"
    )
    draw.line((28, footer_y - 10, WIDTH - 28, footer_y - 10), fill="#45474d", width=1)
    draw.text((28, footer_y), footer, MUTED, small_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def draw_mover(
    draw: ImageDraw.ImageDraw,
    mover: MarketMover,
    rank: int,
    left_x: int,
    value_x: int,
    y: int,
    change_color: str,
    primary_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    secondary_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    draw.text((left_x, y), f"{rank}. {mover.symbol}", TEXT, primary_font)
    draw.text((value_x, y), f"{mover.change_percent:+.2%}", change_color, primary_font)
    draw.text((left_x, y + 24), format_market_cap(mover.market_cap), MUTED, secondary_font)
    draw.text((value_x, y + 24), f"${mover.price:,.2f}", TEXT, secondary_font)


def load_font(
    size: int, *, bold: bool = False, mono: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if mono:
        filename = "DejaVuSansMono.ttf"
    elif bold:
        filename = "DejaVuSans-Bold.ttf"
    else:
        filename = "DejaVuSans.ttf"

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("C:/Windows/Fonts") / ("consola.ttf" if mono else "arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    try:
        return ImageFont.truetype(filename, size=size)
    except OSError:
        return ImageFont.load_default(size=size)
