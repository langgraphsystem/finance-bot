"""Shared notification dispatch helpers (send, dedup, timezone window)."""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.core.db import redis

logger = logging.getLogger(__name__)

# Singleton bot instance — reused across all notification sends to avoid
# creating a new aiohttp session per message (which leaks file descriptors).
_bot_instance = None
_bot_lock = asyncio.Lock()

# Telegram error codes that are worth retrying (transient server/rate errors).
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


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


async def _get_bot():
    """Return singleton Bot instance, creating it on first call."""
    global _bot_instance
    if _bot_instance is not None:
        return _bot_instance
    async with _bot_lock:
        if _bot_instance is None:
            from aiogram import Bot
            from src.core.config import settings
            _bot_instance = Bot(token=settings.telegram_bot_token)
        return _bot_instance


async def send_telegram_message(telegram_id: int, text: str) -> None:
    """Send a message via Telegram Bot API with retry on transient errors.

    Raises on permanent failure so callers know the message was NOT delivered
    and can avoid marking reminders as done / advancing recurrence.
    """
    from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

    bot = await _get_bot()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
            )
            return  # success
        except TelegramRetryAfter as e:
            # Respect Telegram's Retry-After header exactly
            wait = float(e.retry_after) if hasattr(e, "retry_after") else _RETRY_BASE_DELAY * attempt
            logger.warning(
                "Telegram rate-limited (429) for %s, waiting %.1fs (attempt %d/%d)",
                telegram_id, wait, attempt, _MAX_RETRIES,
            )
            last_exc = e
            await asyncio.sleep(wait)
        except TelegramAPIError as e:
            status = getattr(e, "status_code", None) or getattr(e, "error_code", None)
            if status in _RETRYABLE_HTTP_CODES and attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Telegram API error %s for %s, retrying in %.1fs (attempt %d/%d): %s",
                    status, telegram_id, delay, attempt, _MAX_RETRIES, e,
                )
                last_exc = e
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Permanent Telegram API error for %s (status=%s): %s",
                    telegram_id, status, e,
                )
                raise
        except Exception as e:
            logger.error("Unexpected error sending Telegram message to %s: %s", telegram_id, e)
            raise

    # All retries exhausted
    logger.error(
        "Failed to send Telegram message to %s after %d attempts: %s",
        telegram_id, _MAX_RETRIES, last_exc,
    )
    raise last_exc  # type: ignore[misc]
