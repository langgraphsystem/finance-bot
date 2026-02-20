"""Demo: generate habit tracker visuals with Pillow and Matplotlib."""

import random
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, timedelta

OUT = Path("/home/user/finance-bot/demo_output")
OUT.mkdir(exist_ok=True)

# ─── Colors ────────────────────────────────────────────────────
BG = "#16161e"
CARD_BG = "#1e1e2e"
GREEN = "#4ade80"
YELLOW = "#fbbf24"
RED = "#ef4444"
BLUE = "#60a5fa"
PURPLE = "#a78bfa"
GRAY = "#555"
LIGHT = "#e0e0e0"
DIM = "#888"


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


# ═════════════════════════════════════════════════════════════════
# 1. PILLOW — Habit Grid Card (monthly view)
# ═════════════════════════════════════════════════════════════════
def pillow_habit_grid():
    W, H = 440, 380
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Card background
    draw.rounded_rectangle([15, 10, W - 15, H - 10], radius=16, fill=CARD_BG)

    # Title
    draw.text((30, 22), "Meditation", fill=LIGHT)
    draw.text((30, 44), "February 2026", fill=DIM)

    # Day headers
    day_labels = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    cell = 42
    gap = 6
    x0, y0 = 30, 80

    for i, d in enumerate(day_labels):
        x = x0 + i * (cell + gap)
        draw.text((x + 12, y0 - 18), d, fill=DIM)

    # Status for 28 days (Feb 2026 starts on Sunday → offset 6)
    statuses = []
    random.seed(42)
    for _ in range(28):
        r = random.random()
        if r < 0.65:
            statuses.append("done")
        elif r < 0.80:
            statuses.append("skip")
        else:
            statuses.append("miss")

    offset = 6  # Sunday start → 6 empty cells before day 1
    color_map = {"done": GREEN, "skip": YELLOW, "miss": hex_to_rgb(RED)}

    for day_idx, status in enumerate(statuses):
        pos = day_idx + offset
        col = pos % 7
        row = pos // 7
        x = x0 + col * (cell + gap)
        y = y0 + row * (cell + gap)
        fill = color_map[status] if isinstance(color_map[status], tuple) else color_map[status]
        draw.rounded_rectangle([x, y, x + cell, y + cell], radius=8, fill=fill)
        # Day number
        draw.text((x + 8, y + 10), str(day_idx + 1), fill=BG)

    # Legend
    ly = H - 52
    legends = [("Done", GREEN), ("Skipped", YELLOW), ("Missed", RED)]
    lx = 30
    for label, color in legends:
        draw.rounded_rectangle([lx, ly, lx + 14, ly + 14], radius=3, fill=color)
        draw.text((lx + 20, ly - 1), label, fill=DIM)
        lx += 100

    # Stats line
    done_count = statuses.count("done")
    draw.text((30, H - 30), f"Streak: 5d  |  Rate: {done_count}/28 ({done_count*100//28}%)", fill=DIM)

    img.save(OUT / "1_pillow_habit_grid.png")
    print("✓ 1_pillow_habit_grid.png")


# ═════════════════════════════════════════════════════════════════
# 2. PILLOW — Multi-habit Dashboard
# ═════════════════════════════════════════════════════════════════
def pillow_multi_habit():
    W, H = 440, 500
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([15, 10, W - 15, H - 10], radius=16, fill=CARD_BG)
    draw.text((30, 22), "Today's Habits", fill=LIGHT)
    draw.text((30, 44), "Thu, Feb 20 2026", fill=DIM)

    habits = [
        ("Meditation", "15 min", GREEN, True, "09:00"),
        ("Workout", "30 min", BLUE, True, "07:30"),
        ("Read", "20 pages", PURPLE, False, "—"),
        ("Water 2.5L", "1.8 / 2.5", "#06b6d4", False, "—"),
        ("Journal", "Evening", YELLOW, False, "—"),
    ]

    y = 80
    for name, detail, color, done, time_str in habits:
        # Row background
        row_bg = "#2a2a3e" if done else "#222233"
        draw.rounded_rectangle([30, y, W - 30, y + 65], radius=10, fill=row_bg)

        # Status circle
        cx, cy = 58, y + 32
        if done:
            draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=color)
            draw.text((cx - 6, cy - 7), "✓", fill=BG)
        else:
            draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=color, width=2)

        # Text
        name_color = LIGHT if not done else DIM
        draw.text((82, y + 12), name, fill=name_color)
        draw.text((82, y + 34), detail, fill=DIM)

        # Time
        if time_str != "—":
            draw.text((W - 80, y + 22), time_str, fill=DIM)

        y += 75

    # Summary
    draw.text((30, H - 40), "2/5 completed  •  3 remaining", fill=DIM)

    img.save(OUT / "2_pillow_multi_habit.png")
    print("✓ 2_pillow_multi_habit.png")


# ═════════════════════════════════════════════════════════════════
# 3. MATPLOTLIB — Habit Streak Timeline
# ═════════════════════════════════════════════════════════════════
def matplotlib_streak():
    random.seed(42)
    days = [date(2026, 2, 1) + timedelta(days=i) for i in range(20)]

    streak = []
    current = 0
    for _ in days:
        if random.random() < 0.78:
            current += 1
        else:
            current = 0
        streak.append(current)

    fig, ax = plt.subplots(figsize=(8, 3.5), facecolor=BG)
    ax.set_facecolor(BG)

    # Area fill
    ax.fill_between(days, streak, alpha=0.25, color=GREEN)
    ax.plot(days, streak, color=GREEN, linewidth=2.5, marker="o", markersize=4)

    # Mark misses
    for i, s in enumerate(streak):
        if s == 0:
            ax.scatter(days[i], 0, color=RED, s=60, zorder=5, edgecolors="white", linewidth=0.5)

    ax.set_title("Meditation — Streak History", color=LIGHT, fontsize=13, pad=12)
    ax.set_ylabel("Consecutive days", color=DIM, fontsize=10)
    ax.tick_params(colors=DIM, labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="y", color="#333", linewidth=0.5, alpha=0.5)

    fig.tight_layout()
    fig.savefig(OUT / "3_matplotlib_streak.png", dpi=150, facecolor=BG)
    plt.close(fig)
    print("✓ 3_matplotlib_streak.png")


# ═════════════════════════════════════════════════════════════════
# 4. MATPLOTLIB — Weekly Completion Bars
# ═════════════════════════════════════════════════════════════════
def matplotlib_weekly_bars():
    habits = ["Meditate", "Workout", "Read", "Water", "Journal"]
    done = [6, 5, 4, 7, 3]
    total = 7
    pct = [d / total for d in done]

    colors = [GREEN, BLUE, PURPLE, "#06b6d4", YELLOW]

    fig, ax = plt.subplots(figsize=(7, 4), facecolor=BG)
    ax.set_facecolor(BG)

    # Background bars (total)
    ax.barh(habits, [1.0] * len(habits), color="#2a2a3e", height=0.55)
    # Completed bars
    bars = ax.barh(habits, pct, color=colors, height=0.55)

    for i, (bar, d) in enumerate(zip(bars, done)):
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{d}/7", va="center", color=LIGHT, fontsize=11)

    ax.set_xlim(0, 1.15)
    ax.set_title("This Week — Habit Completion", color=LIGHT, fontsize=13, pad=12)
    ax.tick_params(colors=DIM, labelsize=11)
    ax.xaxis.set_visible(False)

    for spine in ax.spines.values():
        spine.set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT / "4_matplotlib_weekly.png", dpi=150, facecolor=BG)
    plt.close(fig)
    print("✓ 4_matplotlib_weekly.png")


# ═════════════════════════════════════════════════════════════════
# 5. PILLOW — Health Summary Card
# ═════════════════════════════════════════════════════════════════
def pillow_health_card():
    W, H = 440, 320
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([15, 10, W - 15, H - 10], radius=16, fill=CARD_BG)
    draw.text((30, 22), "Health Dashboard", fill=LIGHT)
    draw.text((30, 44), "Feb 20, 2026", fill=DIM)

    metrics = [
        ("💧 Water", "2.1L / 2.5L", BLUE, 0.84),
        ("😴 Sleep", "7.2h / 8h", PURPLE, 0.90),
        ("🏃 Steps", "8,400 / 10,000", GREEN, 0.84),
        ("🧘 Meditation", "15m / 15m", YELLOW, 1.0),
    ]

    y = 78
    bar_x = 30
    bar_w = W - 75

    for label, val, color, pct in metrics:
        draw.text((bar_x, y), label, fill=LIGHT)
        draw.text((bar_x + 200, y), val, fill=DIM)

        # Background bar
        by = y + 24
        draw.rounded_rectangle([bar_x, by, bar_x + bar_w, by + 12], radius=6, fill="#2a2a3e")
        # Fill bar
        fill_w = max(12, int(bar_w * pct))
        draw.rounded_rectangle([bar_x, by, bar_x + fill_w, by + 12], radius=6, fill=color)
        # Percentage
        draw.text((bar_x + bar_w + 8, by - 4), f"{int(pct*100)}%", fill=DIM)

        y += 52

    img.save(OUT / "5_pillow_health_card.png")
    print("✓ 5_pillow_health_card.png")


if __name__ == "__main__":
    pillow_habit_grid()
    pillow_multi_habit()
    matplotlib_streak()
    matplotlib_weekly_bars()
    pillow_health_card()
    print(f"\nAll images saved to {OUT}/")
