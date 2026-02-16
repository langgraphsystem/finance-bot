"""Life-tracking helper functions."""

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.enums import LifeEventType
from src.core.models.life_event import LifeEvent
from src.core.models.user_context import UserContext

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
            stmt = stmt.where(LifeEvent.text.ilike(f"%{search_text}%"))

        stmt = stmt.order_by(LifeEvent.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())


def format_timeline(events: list[LifeEvent]) -> str:
    """Format life events as a readable timeline."""
    if not events:
        return "Ничего не найдено."

    lines = []
    current_date = None

    for event in sorted(events, key=lambda e: e.created_at, reverse=True):
        if event.date != current_date:
            current_date = event.date
            lines.append(f"\n<b>{current_date.strftime('%d.%m.%Y')}</b>")

        icon = _type_icon(event.type)
        time_str = event.created_at.strftime("%H:%M") if event.created_at else ""
        text = event.text or ""
        if len(text) > 100:
            text = text[:100] + "..."

        tag_str = ""
        if event.tags:
            tag_str = " " + " ".join(f"#{t}" for t in event.tags)

        lines.append(f"  {time_str} {icon} {text}{tag_str}")

    return "\n".join(lines).strip()


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
    """Format a receipt-style confirmation."""
    icon = _type_icon(event_type)
    tag_str = ""
    if tags:
        tag_str = " [" + ", ".join(tags) + "]"
    short_text = text[:80] if text else ""
    return f"{icon} {short_text}{tag_str}"
