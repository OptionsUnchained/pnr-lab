from __future__ import annotations

import math
from datetime import date
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from expected_move_bot.gex import (
    ExpiryGexRow,
    GexExpirySnapshot,
    GexStrikeSnapshot,
    StrikeGexRow,
    gex_bias_label,
)
from expected_move_bot.movers_image import load_font

WIDTH = 1080
HEIGHT = 1080
BACKGROUND = "#1c2023"
TEXT = "#f1f3f5"
MUTED = "#91a0ad"
GRID = "#41474c"
GREEN = "#63e6a0"
RED = "#ff454b"
BLUE = "#56b4e9"

PLOT_LEFT = 68
PLOT_RIGHT = 914
PLOT_TOP = 313
PLOT_BOTTOM = 856


def render_gex_expiry(snapshot: GexExpirySnapshot) -> bytes:
    image, draw = base_chart(
        snapshot.symbol,
        snapshot.description,
        snapshot.price,
        snapshot.change,
        snapshot.change_percent,
        snapshot.as_of.date(),
        "GEX BY EXPIRY",
        snapshot.total_gex,
        snapshot.gex_bias,
        snapshot.earnings_date,
        snapshot.earnings_confirmed,
        snapshot.earnings_calculated,
    )
    scale = draw_axis(draw, expiry_extreme(snapshot.rows))
    draw_expiry_bars(image, draw, snapshot.rows, scale)
    draw_legend(draw, PLOT_LEFT, 778)
    return finish_chart(
        image,
        draw,
        snapshot.contracts_received,
        snapshot.contracts_requested,
    )


def render_gex_strikes(snapshot: GexStrikeSnapshot) -> bytes:
    expiration_dte = (snapshot.expiration_date - snapshot.as_of.date()).days
    title = (
        f"GEX BY STRIKE · {snapshot.expiration_date:%b} "
        f"{snapshot.expiration_date.day} · {expiration_dte} DTE"
    )
    image, draw = base_chart(
        snapshot.symbol,
        snapshot.description,
        snapshot.price,
        snapshot.change,
        snapshot.change_percent,
        snapshot.as_of.date(),
        title.upper(),
        snapshot.total_gex,
        snapshot.gex_bias,
        snapshot.earnings_date,
        snapshot.earnings_confirmed,
        snapshot.earnings_calculated,
    )
    scale = draw_axis(draw, strike_extreme(snapshot.rows))
    draw_strike_bars(image, draw, snapshot.rows, snapshot.price, scale)
    draw_legend(draw, PLOT_LEFT, 778)
    return finish_chart(
        image,
        draw,
        snapshot.contracts_received,
        snapshot.contracts_requested,
    )


def base_chart(
    symbol: str,
    description: str,
    price: float,
    change: float | None,
    change_percent: float | None,
    chart_date: date,
    chart_title: str,
    total_gex: float,
    gex_bias: float,
    earnings_date: date | None,
    earnings_confirmed: bool,
    earnings_calculated: bool,
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    symbol_font = load_font(64, bold=True)
    description_font = load_font(31)
    earnings_font = load_font(23, bold=True)
    price_font = load_font(53, bold=True)
    change_font = load_font(28, bold=True)
    date_font = load_font(26)
    chart_title_font = load_font(30, bold=True)
    bias_font = load_font(19, bold=True)

    draw.text((59, 50), symbol, TEXT, symbol_font)
    draw.text((59, 132), trim_text(description, 43), TEXT, description_font)
    draw.text(
        (59, 181),
        earnings_header(
            earnings_date,
            chart_date,
            confirmed=earnings_confirmed,
            calculated=earnings_calculated,
        ),
        MUTED,
        earnings_font,
    )

    price_text = f"${price:,.2f}"
    draw.text((1018, 51), price_text, TEXT, price_font, anchor="ra")
    if change is not None:
        color = GREEN if change >= 0 else RED
        if change_percent is None:
            change_text = f"{change:+.2f}"
        else:
            change_text = f"{change:+.2f} ({change_percent:+.2%})"
        draw.text((1018, 119), change_text, color, change_font, anchor="ra")
    draw.text(
        (1018, 160),
        f"{chart_date:%b} {chart_date.day}",
        MUTED,
        date_font,
        anchor="ra",
    )

    draw.text((59, 232), chart_title, TEXT, chart_title_font)
    total_color = GREEN if total_gex >= 0 else RED
    draw.text(
        (1018, 232),
        f"TOTAL {format_gex(total_gex)}",
        total_color,
        chart_title_font,
        anchor="ra",
    )
    bias_label = gex_bias_label(gex_bias)
    bias_color = MUTED if bias_label == "Balanced" else (GREEN if gex_bias > 0 else RED)
    draw.text(
        (1018, 274),
        f"BIAS {gex_bias:+.0%} · {bias_label.upper()}",
        bias_color,
        bias_font,
        anchor="ra",
    )
    return image, draw


def draw_axis(draw: ImageDraw.ImageDraw, extreme: float):
    bound = nice_bound(max(extreme, 1.0) * 1.08)
    axis_font = load_font(26)

    def y_position(value: float) -> float:
        return PLOT_TOP + (bound - value) / (2 * bound) * (PLOT_BOTTOM - PLOT_TOP)

    for value in (bound, bound / 2, 0.0, -bound / 2, -bound):
        y = round(y_position(value))
        color = "#687078" if value == 0 else GRID
        width = 2 if value == 0 else 1
        draw.line((PLOT_LEFT, y, PLOT_RIGHT, y), fill=color, width=width)
        draw.text(
            (929, y),
            format_axis_value(value),
            MUTED,
            axis_font,
            anchor="lm",
        )
    return y_position


def draw_expiry_bars(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rows: list[ExpiryGexRow],
    y_position,
) -> None:
    zero_y = y_position(0)
    step = (PLOT_RIGHT - PLOT_LEFT) / max(len(rows), 1)
    bar_width = max(3, min(12, int(step * 0.32)))
    label_size, label_angle = expiry_label_style(step)
    label_font = load_font(label_size)
    for index, row in enumerate(rows):
        center = PLOT_LEFT + (index + 0.5) * step
        draw.line(
            (round(center), PLOT_TOP, round(center), PLOT_BOTTOM),
            fill="#30363b",
            width=1,
        )
        draw_bar(draw, center - bar_width, row.call_gex, zero_y, y_position, bar_width, GREEN)
        draw_bar(draw, center, row.put_gex, zero_y, y_position, bar_width, RED)
        draw_centered_rotated_text(
            image,
            (round(center), PLOT_BOTTOM + 14),
            expiry_label(row.expiration_date),
            label_font,
            TEXT,
            angle=label_angle,
        )


def draw_strike_bars(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rows: list[StrikeGexRow],
    spot_price: float,
    y_position,
) -> None:
    strikes = [row.strike for row in rows]
    minimum, maximum = min(strikes), max(strikes)
    if math.isclose(minimum, maximum):
        minimum -= 1
        maximum += 1
    padding = (maximum - minimum) * 0.015
    domain_min, domain_max = minimum - padding, maximum + padding

    def x_position(strike: float) -> float:
        return PLOT_LEFT + (strike - domain_min) / (domain_max - domain_min) * (
            PLOT_RIGHT - PLOT_LEFT
        )

    tick_values = strike_tick_values(minimum, maximum)
    for strike in tick_values:
        x = round(x_position(strike))
        draw.line((x, PLOT_TOP, x, PLOT_BOTTOM), fill="#30363b", width=1)

    differences = [b - a for a, b in zip(strikes, strikes[1:], strict=False) if b > a]
    typical_step = sorted(differences)[len(differences) // 2] if differences else 1.0
    pixel_step = typical_step / (domain_max - domain_min) * (PLOT_RIGHT - PLOT_LEFT)
    bar_width = max(2, min(10, int(pixel_step * 0.34)))
    zero_y = y_position(0)
    for row in rows:
        center = x_position(row.strike)
        draw_bar(draw, center - bar_width, row.call_gex, zero_y, y_position, bar_width, GREEN)
        draw_bar(draw, center, row.put_gex, zero_y, y_position, bar_width, RED)

    call_wall = max(rows, key=lambda row: row.call_gex)
    put_wall = min(rows, key=lambda row: row.put_gex)
    if put_wall.put_gex < 0:
        draw_vertical_marker(draw, x_position(put_wall.strike), RED)
    if call_wall.call_gex > 0:
        draw_vertical_marker(draw, x_position(call_wall.strike), GREEN)
    if domain_min <= spot_price <= domain_max:
        spot_x = x_position(spot_price)
        draw_vertical_marker(draw, spot_x, BLUE)
        draw.text(
            (spot_x - 8, PLOT_TOP + 2),
            f"${spot_price:,.0f}",
            BLUE,
            load_font(26, bold=True),
            anchor="ra",
        )

    highlighted: dict[float, str] = {}
    if call_wall.call_gex > 0:
        highlighted[call_wall.strike] = GREEN
    if put_wall.put_gex < 0:
        highlighted[put_wall.strike] = RED

    # Regular $10 strike guides make each bar's strike readable. Exact wall
    # strikes remain labeled in color, even when they fall between guides.
    regular_labels = [
        strike
        for strike in tick_values
        if all(abs(x_position(strike) - x_position(wall)) >= 42 for wall in highlighted)
    ]
    labels = [(strike, TEXT) for strike in regular_labels]
    labels.extend(highlighted.items())
    label_font = load_font(21 if len(labels) > 18 else 24)
    for strike, color in sorted(labels):
        draw_centered_rotated_text(
            image,
            (round(x_position(strike)), PLOT_BOTTOM + 20),
            format_strike(strike),
            label_font,
            color,
        )


def draw_bar(draw, x: float, value: float, zero_y: float, y_position, width: int, color: str):
    value_y = y_position(value)
    top, bottom = sorted((round(zero_y), round(value_y)))
    if top == bottom and value != 0:
        bottom += 1
    draw.rectangle((round(x), top, round(x) + width, bottom), fill=color)


def draw_vertical_marker(draw: ImageDraw.ImageDraw, x: float, color: str) -> None:
    start = PLOT_TOP + 4
    while start < PLOT_BOTTOM:
        draw.line((round(x), start, round(x), min(start + 9, PLOT_BOTTOM)), fill=color, width=2)
        start += 17


def draw_legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    font = load_font(25)
    draw.rectangle((x, y, x + 19, y + 19), fill=GREEN)
    draw.text((x + 28, y - 5), "Call", TEXT, font)
    draw.rectangle((x, y + 34, x + 19, y + 53), fill=RED)
    draw.text((x + 28, y + 29), "Put", TEXT, font)


def finish_chart(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    contracts_received: int,
    contracts_requested: int,
) -> bytes:
    brand_font = load_font(29, bold=True)
    footer_font = load_font(22)
    small_font = load_font(17)
    guide_font = load_font(15)
    draw.text(
        (1018, 957),
        "BIAS GUIDE · <10% BAL · 10–30% SLIGHT · 30–60% MOD · ≥60% STRONG",
        MUTED,
        guide_font,
        anchor="ra",
    )
    draw.text((59, 992), "OPTIONS UNCHAINED", TEXT, brand_font)
    draw.text((1018, 991), "SOURCE: TASTYTRADE", MUTED, footer_font, anchor="ra")
    draw.text(
        (1018, 1025),
        (
            "Dealer-positioning proxy · OI updates daily · "
            f"{contracts_received}/{contracts_requested} contracts"
        ),
        MUTED,
        small_font,
        anchor="ra",
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def draw_centered_rotated_text(
    image: Image.Image,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    *,
    angle: float = 45,
) -> None:
    left, top, right, bottom = font.getbbox(text)
    label = Image.new("RGBA", (right - left + 8, bottom - top + 8), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4 - left, 4 - top), text, fill=fill, font=font)
    rotated = label.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    x, y = position
    image.paste(rotated, (round(x - rotated.width / 2), y), rotated)


def expiry_extreme(rows: list[ExpiryGexRow]) -> float:
    return max((max(row.call_gex, abs(row.put_gex)) for row in rows), default=1.0)


def strike_extreme(rows: list[StrikeGexRow]) -> float:
    return max((max(row.call_gex, abs(row.put_gex)) for row in rows), default=1.0)


def nice_bound(value: float) -> float:
    exponent = math.floor(math.log10(value))
    fraction = value / 10**exponent
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * 10**exponent


def format_axis_value(value: float) -> str:
    if value == 0:
        return "$0"
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${sign}{absolute / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"${sign}{absolute / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"${sign}{absolute / 1_000:.1f}K"
    return f"${sign}{absolute:.0f}"


def format_gex(value: float) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${sign}{absolute / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"${sign}{absolute / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"${sign}{absolute / 1_000:.1f}K"
    return f"${sign}{absolute:.0f}"


def expiry_label_style(pixel_step: float) -> tuple[int, int]:
    """Choose a readable font and angle while retaining every expiry label."""
    if pixel_step >= 55:
        return 23, 45
    if pixel_step >= 34:
        return 18, 65
    return 15, 90


def strike_tick_values(minimum: float, maximum: float) -> list[float]:
    """Return regular strike labels, preferring $10 intervals for stocks."""
    span = max(maximum - minimum, 0.0)
    if span == 0:
        return [minimum]

    if maximum <= 50 or span < 30:
        required_step = span / 16
        candidates = (0.5, 1, 2, 2.5, 5, 10)
    elif span <= 240:
        required_step = 10
        candidates = (10,)
    else:
        required_step = span / 24
        candidates = (10, 20, 25, 50, 100, 200, 250, 500, 1000)
    step = next(
        (candidate for candidate in candidates if candidate >= required_step),
        candidates[-1],
    )

    first = math.ceil(minimum / step) * step
    last = math.floor(maximum / step) * step
    count = max(0, round((last - first) / step) + 1)
    return [round(first + index * step, 8) for index in range(count)]


def expiry_label(expiration: date) -> str:
    if expiration.month == 1:
        return f"Jan '{expiration.strftime('%y')}"
    return f"{expiration:%b} {expiration.day}"


def format_strike(strike: float) -> str:
    return f"${strike:,.0f}" if strike.is_integer() else f"${strike:,.2f}"


def trim_text(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else f"{value[: maximum - 1]}…"


def earnings_header(
    report_date: date | None,
    as_of: date,
    *,
    confirmed: bool,
    calculated: bool,
) -> str:
    if report_date is None:
        return "EARNINGS · N/A"
    estimate_prefix = "~ " if calculated else ""
    # Use a monochrome check supported by the bundled chart font. Color-emoji
    # glyphs render as an empty square in Pillow on the Railway image.
    confirmation = " ✓" if confirmed else ""
    dte = (report_date - as_of).days
    return (
        f"EARNINGS · {estimate_prefix}{report_date:%b} {report_date.day}, "
        f"{report_date.year}{confirmation} · {dte} DTE"
    ).upper()
