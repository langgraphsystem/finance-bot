"""Life-tracking helper functions."""

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.enums import LifeEventType
from src.core.models.life_event import LifeEvent
from src.core.models.user_context import UserContext
from src.core.search_utils import ilike_all_words, split_search_words

logger = logging.getLogger(__name__)

DEFAULT_COMM_MODE = "receipt"


async def get_communication_mode(user_id: str) -> str:
    """Get user's communication mode from user_context.preferences."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserContext.preferences).where(UserContext.user_id == uuid.UUID(user_id))
            )
            prefs = result.scalar_one_or_none()
            if prefs and isinstance(prefs, dict):
                return prefs.get("communication_mode", DEFAULT_COMM_MODE)
    except Exception as e:
        logger.warning("Failed to get comm mode: %s", e)
    return DEFAULT_COMM_MODE


async def set_communication_mode(user_id: str, mode: str) -> None:
    """Set user's communication mode in user_context.preferences."""
    async with async_session() as session:
        result = await session.execute(
            select(UserContext).where(UserContext.user_id == uuid.UUID(user_id))
        )
        ctx = result.scalar_one_or_none()
        if ctx:
            prefs = ctx.preferences or {}
            prefs["communication_mode"] = mode
            ctx.preferences = prefs
            await session.commit()


async def save_life_event(
    family_id: str,
    user_id: str,
    event_type: LifeEventType,
    text: str | None = None,
    tags: list[str] | None = None,
    data: dict[str, Any] | None = None,
    event_date: date | None = None,
) -> LifeEvent:
    """Save a life event to the database."""
    async with async_session() as session:
        event = LifeEvent(
            family_id=uuid.UUID(family_id),
            user_id=uuid.UUID(user_id),
            type=event_type,
            date=event_date or date.today(),
            text=text,
            tags=tags,
            data=data,
        )
        session.add(event)
        await session.commit()
        return event


async def query_life_events(
    family_id: str,
    user_id: str | None = None,
    event_type: LifeEventType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    tags: list[str] | None = None,
    search_text: str | None = None,
    limit: int = 50,
) -> list[LifeEvent]:
    """Query life events with filters."""
    async with async_session() as session:
        stmt = select(LifeEvent).where(LifeEvent.family_id == uuid.UUID(family_id))

        if user_id:
            stmt = stmt.where(LifeEvent.user_id == uuid.UUID(user_id))
        if event_type:
            stmt = stmt.where(LifeEvent.type == event_type)
        if date_from:
            stmt = stmt.where(LifeEvent.date >= date_from)
        if date_to:
            stmt = stmt.where(LifeEvent.date <= date_to)
        if tags:
            # JSONB containment: tags @> '["tag1"]'
            stmt = stmt.where(LifeEvent.tags.op("@>")(tags))
        if search_text:
            words = split_search_words(search_text)
            if words:
                stmt = stmt.where(ilike_all_words(LifeEvent.text, words))
            else:
                stmt = stmt.where(LifeEvent.text.ilike(f"%{search_text}%"))

        stmt = stmt.order_by(LifeEvent.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _parse_date(val: str | None) -> date | None:
    """Parse YYYY-MM-DD string to date, return None on failure."""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def resolve_life_period(
    intent_data: dict[str, Any],
) -> tuple[date | None, date | None, str]:
    """Resolve period from intent_data for life event queries.

    Returns (date_from, date_to, label). None dates mean "no filter".
    Both dates are inclusive (suitable for query_life_events >= / <=).
    """
    period = intent_data.get("period")
    if not period:
        return None, None, ""

    today = date.today()

    if period == "today":
        return today, today, "сегодня"

    if period == "day":
        d = _parse_date(intent_data.get("date")) or today
        return d, d, d.strftime("%d.%m.%Y")

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today, "эту неделю"

    if period == "prev_week":
        end = today - timedelta(days=today.weekday()) - timedelta(days=1)
        start = end - timedelta(days=6)
        return start, end, "прошлую неделю"

    if period == "month":
        start = today.replace(day=1)
        return start, today, "этот месяц"

    if period == "prev_month":
        first = today.replace(day=1)
        last_day = first - timedelta(days=1)
        start = last_day.replace(day=1)
        return start, last_day, "прошлый месяц"

    if period == "year":
        return today.replace(month=1, day=1), today, "этот год"

    if period == "custom":
        df = _parse_date(intent_data.get("date_from"))
        dt = _parse_date(intent_data.get("date_to"))
        if df and dt:
            label = f"{df.strftime('%d.%m')} – {dt.strftime('%d.%m.%Y')}"
            return df, dt, label
        if df:
            return df, today, f"с {df.strftime('%d.%m.%Y')}"

    return None, None, ""


def format_timeline(events: list, max_events: int = 20) -> str:
    """Format life events as a rich Telegram HTML timeline."""
    if not events:
        return "Ничего не найдено."

    total = len(events)
    display = sorted(events, key=lambda e: e.created_at, reverse=True)[:max_events]
    lines: list[str] = []
    current_date = None

    for event in display:
        if event.date != current_date:
            current_date = event.date
            lines.append(f"\n<b>{current_date.strftime('%d.%m.%Y')}</b>")

        icon = _type_icon(event.type)
        time_str = event.created_at.strftime("%H:%M") if event.created_at else ""
        text = _format_event_text(event)

        tag_str = ""
        if event.tags:
            tag_str = " " + " ".join(f"<i>#{t}</i>" for t in event.tags)

        lines.append(f"  {time_str} {icon} {text}{tag_str}")

    result = "\n".join(lines).strip()

    if total > max_events:
        result += f"\n\n<i>... и ещё {total - max_events} записей</i>"

    return result


def _format_event_text(event) -> str:
    """Format event text with type-specific rendering."""
    text = event.text or ""
    data = getattr(event, "data", None) or {}

    if event.type == LifeEventType.mood and isinstance(data, dict):
        parts = []
        if "mood" in data:
            parts.append(f"\U0001f60a{data['mood']}")
        if "energy" in data:
            parts.append(f"\u26a1{data['energy']}")
        if "stress" in data:
            parts.append(f"\U0001f630{data['stress']}")
        if "sleep_hours" in data:
            parts.append(f"\U0001f634{data['sleep_hours']}h")
        return " ".join(parts) if parts else text[:80]

    if event.type == LifeEventType.task and isinstance(data, dict):
        done = "\u2705" if data.get("done") else "\u2b1c"
        return f"{done} {text[:80]}"

    if event.type == LifeEventType.drink and isinstance(data, dict):
        item = data.get("item", "")
        count = data.get("count", 1)
        vol = data.get("volume_ml", 0)
        if item:
            r = item
            if count and int(count) > 1:
                r += f" x{count}"
            if vol:
                r += f" ({int(vol) * int(count or 1)}ml)"
            return r

    if event.type == LifeEventType.food and isinstance(data, dict):
        meal = data.get("meal_type", "")
        food = data.get("food_item", text)
        if meal:
            return f"<i>{meal}</i>: {str(food)[:60]}"
        return str(food)[:80]

    if len(text) > 100:
        return text[:100] + "..."
    return text


def _type_icon(event_type: LifeEventType) -> str:
    """Get emoji icon for event type."""
    icons = {
        LifeEventType.note: "\U0001f4dd",
        LifeEventType.food: "\U0001f37d",
        LifeEventType.drink: "\u2615",
        LifeEventType.mood: "\U0001f60a",
        LifeEventType.task: "\u2705",
        LifeEventType.reflection: "\U0001f319",
    }
    return icons.get(event_type, "\U0001f4cc")


async def auto_tag(text: str) -> list[str]:
    """Auto-generate tags from text using Gemini Flash."""
    try:
        from src.core.llm.clients import google_client

        client = google_client()
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=f"""Извлеки 1-3 тега из текста. Верни ТОЛЬКО теги через запятую, без #.
Пример: "идея: сделать лендинг для финбота" -> finbot, идея, лендинг
Пример: "запомнить: купить молоко" -> покупки
Текст: {text}""",
        )
        raw = response.text.strip()
        tags = [t.strip().lower() for t in raw.split(",") if t.strip()]
        return tags[:3]
    except Exception as e:
        logger.warning("Auto-tag failed: %s", e)
        return []


def format_receipt(event_type: LifeEventType, text: str, tags: list[str] | None) -> str:
    """Format a receipt-style confirmation (legacy, plain text)."""
    icon = _type_icon(event_type)
    tag_str = ""
    if tags:
        tag_str = " [" + ", ".join(tags) + "]"
    short_text = text[:80] if text else ""
    return f"{icon} {short_text}{tag_str}"


_TYPE_LABELS = {
    LifeEventType.note: "Заметка",
    LifeEventType.food: "Питание",
    LifeEventType.drink: "Напиток",
    LifeEventType.mood: "Чек-ин",
    LifeEventType.task: "Задача",
    LifeEventType.reflection: "Рефлексия",
}


def format_save_response(
    event_type: LifeEventType,
    text: str,
    tags: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Format a rich HTML confirmation for saved life events."""
    icon = _type_icon(event_type)
    label = _TYPE_LABELS.get(event_type, "Запись")
    result = f"{icon} <b>{label}</b>\n"

    if event_type == LifeEventType.mood and data:
        for key, emoji, name in [
            ("mood", "\U0001f60a", "Настроение"),
            ("energy", "\u26a1", "Энергия"),
            ("stress", "\U0001f630", "Стресс"),
        ]:
            if key in data:
                val = int(data[key])
                bar = "\u2588" * val + "\u2591" * (10 - val)
                result += f"  {emoji} {name}: {bar} {val}/10\n"
        if "sleep_hours" in data:
            result += f"  \U0001f634 Сон: {data['sleep_hours']}ч\n"
    elif event_type == LifeEventType.drink and data:
        item = data.get("item", text)
        count = data.get("count", 1)
        vol = data.get("volume_ml", 0)
        line = f"  {item}"
        if count and int(count) > 1:
            line += f" x{count}"
        if vol:
            line += f" ({int(vol) * int(count or 1)}ml)"
        result += line + "\n"
    elif event_type == LifeEventType.food and data:
        meal = data.get("meal_type", "")
        food = data.get("food_item", text)
        if meal:
            result += f"  <i>{meal}</i>: {food}\n"
        else:
            result += f"  {food}\n"
    else:
        short = text[:120] if len(text) > 120 else text
        result += f"  {short}\n"
        if len(text) > 120:
            result += "  ...\n"

    if tags:
        result += "  " + " ".join(f"<i>#{t}</i>" for t in tags)

    return result.rstrip()
