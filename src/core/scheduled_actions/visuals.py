"""Visual generator for Scheduled Intelligence Actions cards."""

import io
import os

from PIL import Image, ImageDraw, ImageFont

# Define a standard font path for Windows fallback
DEFAULT_FONT_PATH = "C:\\Windows\\Fonts\\arial.ttf"
FALLBACK_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def _get_font(size: int):
    """Load font with size, fall back to default if not found."""
    try:
        if os.path.exists(DEFAULT_FONT_PATH):
            return ImageFont.truetype(DEFAULT_FONT_PATH, size)
        if os.path.exists(FALLBACK_FONT_PATH):
            return ImageFont.truetype(FALLBACK_FONT_PATH, size)
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def draw_rounded_rect(draw, coords, radius, fill):
    """Helper to draw a rounded rectangle."""
    x1, y1, x2, y2 = coords
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.pieslice([x1, y1, x1 + radius * 2, y1 + radius * 2], 180, 270, fill=fill)
    draw.pieslice([x2 - radius * 2, y1, x2, y1 + radius * 2], 270, 360, fill=fill)
    draw.pieslice([x1, y2 - radius * 2, x1 + radius * 2, y2], 90, 180, fill=fill)
    draw.pieslice([x2 - radius * 2, y2 - radius * 2, x2, y2], 0, 90, fill=fill)

def generate_budget_card(spent: float, budget: float, language: str = "en") -> io.BytesIO:
    """Generate a beautiful PNG card for budget status."""
    width, height = 600, 250
    ratio = min(1.0, spent / budget) if budget > 0 else 0

    # Colors
    bg_color = (18, 24, 38)  # Deep dark blue
    card_color = (30, 41, 59)  # Slate blue
    text_color = (248, 250, 252)
    secondary_text = (148, 163, 184)

    if ratio >= 1.0:
        bar_color = (239, 68, 68)  # Red
    elif ratio >= 0.8:
        bar_color = (245, 158, 11)  # Orange/Amber
    else:
        bar_color = (34, 197, 94)  # Green

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Main card body
    draw_rounded_rect(draw, [20, 20, 580, 230], 15, card_color)

    # Header
    title_font = _get_font(28)
    labels = {
        "en": "Monthly Budget",
        "ru": "Месячный бюджет",
        "es": "Presupuesto mensual",
    }
    title_text = labels.get(language, labels["en"])
    draw.text((50, 45), title_text, font=title_font, fill=text_color)

    # Amount text
    amount_font = _get_font(42)
    spent_text = f"${spent:,.2f}"
    total_text = f" / ${budget:,.2f}"

    # Draw spent amount
    draw.text((50, 85), spent_text, font=amount_font, fill=text_color)
    # Draw total after spent (spacing)
    spent_w = draw.textlength(spent_text, font=amount_font)
    draw.text((50 + spent_w, 95), total_text, font=_get_font(24), fill=secondary_text)

    # Progress Bar Background
    bar_x1, bar_y1, bar_x2, bar_y2 = 50, 160, 550, 185
    draw_rounded_rect(draw, [bar_x1, bar_y1, bar_x2, bar_y2], 12, (51, 65, 85))

    # Progress Bar Fill
    if ratio > 0:
        fill_w = max(24, int((bar_x2 - bar_x1) * ratio))
        draw_rounded_rect(draw, [bar_x1, bar_y1, bar_x1 + fill_w, bar_y2], 12, bar_color)

    # Percentage
    pct_font = _get_font(24)
    pct_text = f"{spent/budget:.1%}" if budget > 0 else "0%"
    draw.text(
        (550 - draw.textlength(pct_text, font=pct_font), 125),
        pct_text,
        font=pct_font,
        fill=bar_color,
    )

    # Save to buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
