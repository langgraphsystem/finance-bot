"""Shared notification dispatch helpers (send, dedup, timezone window)."""

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.core.db import redis

logger = logging.getLogger(__name__)


def normalize_timezone(timezone: str | None) -> str:
    """Normalize timezone, falling back to UTC when invalid."""
    tz_name = (timezone or "").strip() or "UTC"
    try:
        ZoneInfo(tz_name)
        return tz_name
    except ZoneInfoNotFoundError:
        return "UTC"


def now_in_timezone(timezone: str) -> datetime:
    """Current datetime in the provided timezone."""
    return datetime.now(UTC).astimezone(ZoneInfo(normalize_timezone(timezone)))


def is_send_window(
    timezone: str,
    *,
    target_hour: int,
    target_minute: int = 0,
    window_minutes: int = 15,
) -> bool:
    """Check whether local time is within the dispatch window."""
    now_local = now_in_timezone(timezone)
    start = now_local.replace(
        hour=target_hour,
        minute=target_minute,
        second=0,
        microsecond=0,
    )
    end = start + timedelta(minutes=window_minutes)
    return start <= now_local < end


async def mark_daily_once(kind: str, user_id: str, day: date) -> bool:
    """Mark daily notification as sent once per user/day. Returns True if first call."""
    key = f"life:{kind}:{user_id}:{day.isoformat()}"
    try:
        was_set = await redis.set(key, "1", ex=172800, nx=True)
        return bool(was_set)
    except Exception:
        return True


async def send_telegram_message(telegram_id: int, text: str) -> None:
    """Send a message via Telegram Bot API."""
    from src.core.config import settings

    try:
        from aiogram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception as e:
        logger.error("Failed to send Telegram message to %s: %s", telegram_id, e)
