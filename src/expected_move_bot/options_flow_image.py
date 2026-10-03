from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from expected_move_bot.gex_image import trim_text
from expected_move_bot.movers_image import load_font
from expected_move_bot.options_flow import OptionsFlowSnapshot, flow_bias_label

WIDTH = 1080
HEIGHT = 1050
BACKGROUND = "#1c2023"
PANEL = "#242a2f"
TEXT = "#f1f3f5"
MUTED = "#91a0ad"
GRID = "#41474c"
GREEN = "#63e6a0"
RED = "#ff454b"
BLUE = "#56b4e9"


def render_options_flow(snapshot: OptionsFlowSnapshot) -> bytes:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    symbol_font = load_font(58, bold=True)
    description_font = load_font(26)
    price_font = load_font(45, bold=True)
    title_font = load_font(27, bold=True)
    summary_font = load_font(19, bold=True)
    header_font = load_font(18, bold=True)
    row_font = load_font(22)
    row_bold = load_font(22, bold=True)
    footer_font = load_font(17)

    draw.text((55, 42), snapshot.symbol, TEXT, symbol_font)
    draw.text((55, 112), trim_text(snapshot.description, 48), TEXT, description_font)
    draw.text((1025, 45), f"${snapshot.price:,.2f}", TEXT, price_font, anchor="ra")
    if snapshot.change is not None:
        color = GREEN if snapshot.change >= 0 else RED
        change = f"{snapshot.change:+.2f}"
        if snapshot.change_percent is not None:
            change += f" ({snapshot.change_percent:+.2%})"
        draw.text((1025, 103), change, color, title_font, anchor="ra")

    dte = (snapshot.expiration_date - snapshot.as_of.date()).days
    draw.text(
        (55, 170),
        f"OPTIONS FLOW · {snapshot.expiration_date:%b} {snapshot.expiration_date.day} · {dte} DTE",
        TEXT,
        title_font,
    )
    draw.text(
        (1025, 170),
        f"TOP 10 · {format_count(snapshot.total_volume)} CONTRACTS",
        BLUE,
        title_font,
        anchor="ra",
    )

    bias = snapshot.directional_bias
    bias_color = MUTED if abs(bias) < 0.10 else (GREEN if bias > 0 else RED)
    draw.rounded_rectangle((55, 224, 1025, 314), radius=12, fill=PANEL)
    draw.text(
        (78, 242),
        f"FLOW BIAS {bias:+.0%} · {flow_bias_label(bias).upper()}",
        bias_color,
        summary_font,
    )
    draw.text(
        (1002, 242),
        f"PREMIUM {format_money(snapshot.total_premium)}",
        MUTED,
        summary_font,
        anchor="ra",
    )
    draw.text(
        (1002, 278),
        f"CLASSIFIED {snapshot.classified_coverage:.0%}",
        MUTED,
        summary_font,
        anchor="ra",
    )

    columns = [
        ("STRIKE", 140, "la"),
        ("VOLUME", 325, "ra"),
        ("PUT B/S", 490, "ra"),
        ("CALL B/S", 670, "ra"),
        ("VOL/OI", 835, "ra"),
        ("PREMIUM", 1005, "ra"),
    ]
    draw.text((72, 341), "#", MUTED, header_font)
    for label, x, anchor in columns:
        draw.text((x, 341), label, MUTED, header_font, anchor=anchor)
    draw.line((55, 378, 1025, 378), fill=GRID, width=2)

    row_height = 56
    for index, row in enumerate(snapshot.rows, start=1):
        y = 401 + (index - 1) * row_height
        if index % 2 == 0:
            draw.rectangle((55, y - 10, 1025, y + 38), fill=PANEL)
        draw.text((72, y), str(index), MUTED, row_font)
        draw.text((140, y), format_strike(row.strike), TEXT, row_bold)
        draw.text((325, y), format_count(row.volume), TEXT, row_font, anchor="ra")
        draw.text((490, y), side_text(row.put_buy, row.put_sell), TEXT, row_font, anchor="ra")
        draw.text((670, y), side_text(row.call_buy, row.call_sell), TEXT, row_font, anchor="ra")
        ratio = "—" if row.volume_oi is None else f"{row.volume_oi:.2f}x"
        draw.text((835, y), ratio, TEXT, row_font, anchor="ra")
        draw.text((1005, y), format_money(row.premium), TEXT, row_font, anchor="ra")

    footer_y = 978
    draw.text((55, footer_y), "OPTIONS UNCHAINED", TEXT, title_font)
    draw.text(
        (1025, footer_y),
        "SOURCE: TASTYTRADE",
        MUTED,
        title_font,
        anchor="ra",
    )
    draw.text(
        (1025, 1016),
        (
            "B/S = ask-side buys / bid-side sells · U = midpoint/unclassified · "
            "Aggressor-flow estimate; not open/close"
        ),
        MUTED,
        footer_font,
        anchor="ra",
    )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def side_text(buy: int, sell: int) -> str:
    total = buy + sell
    if not total:
        return "—"
    return f"{format_count(buy)}/{format_count(sell)}"


def format_count(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,}"


def format_money(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def format_strike(value: float) -> str:
    return f"${value:,.0f}" if value.is_integer() else f"${value:,.2f}"
