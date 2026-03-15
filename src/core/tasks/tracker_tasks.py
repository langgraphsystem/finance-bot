"""Tracker reminder cron task — sends daily reminders for unlogged trackers.

Runs every minute. For each active tracker with reminder_enabled=true:
  1. Converts reminder_time (HH:MM) to user's local timezone
  2. Fires within a 1-minute window of the scheduled time (one-shot mode)
     OR fires whenever dedup key expires (repeat mode — until logged today)
  3. Skips if tracker is already logged today (goal-aware for sum mode)
  4. Uses Redis dedup key to rate-limit sends:
       - One-shot: dedup TTL = 25h (fires exactly once per day)
       - Repeat mode (reminder_repeat_minutes > 0):
           * dedup TTL = reminder_repeat_minutes * 60 → fires again after interval
           * Once logged → dedup reset with 25h TTL → stops for the day
"""

import logging
from datetime import UTC, date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB

from src.core.db import async_session
from src.core.locale_resolution import resolve_notification_locale
from src.core.models.tracker import Tracker, TrackerEntry
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.notifications_pkg.dispatch import send_telegram_message
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

# Redis TTL for dedup keys: 25 h — clears before next day's reminder window
_DEDUP_TTL = 60 * 60 * 25

_REMINDER_TEXT = {
    "en": "⏰ Don't forget to log your {emoji} <b>{name}</b> today!",
    "ru": "⏰ Не забудь записать {emoji} <b>{name}</b> сегодня!",
    "es": "⏰ ¡No olvides registrar {emoji} <b>{name}</b> hoy!",
}

_REMINDER_TEXT_REPEAT = {
    "en": "⏰ {emoji} <b>{name}</b> — still not logged today. Log it now!",
    "ru": "⏰ {emoji} <b>{name}</b> — ещё не записано сегодня. Запишите!",
    "es": "⏰ {emoji} <b>{name}</b> — aún sin registrar hoy. ¡Regístralo!",
}


def _reminder_text(lang: str, emoji: str, name: str, is_repeat: bool = False) -> str:
    templates = _REMINDER_TEXT_REPEAT if is_repeat else _REMINDER_TEXT
    tmpl = templates.get(lang, templates["en"])
    return tmpl.format(emoji=emoji, name=name)


def _parse_tz(tz_str: str | None) -> timezone:
    """Return ZoneInfo for tz_str, falling back to UTC."""
    if not tz_str:
        return UTC
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception):
        return UTC


def _matches_reminder_time(reminder_time: str, now_local: datetime) -> bool:
    """Return True if HH:MM reminder_time matches now_local within the current minute (one-shot)."""
    try:
        h, m = map(int, reminder_time.split(":"))
        return now_local.hour == h and now_local.minute == m
    except (ValueError, AttributeError):
        return False


def _is_past_reminder_time(reminder_time: str, now_local: datetime) -> bool:
    """Return True if we are at or past reminder_time today (for repeat mode)."""
    try:
        h, m = map(int, reminder_time.split(":"))
        reminder_dt = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        return now_local >= reminder_dt
    except (ValueError, AttributeError):
        return False


@broker.task(schedule=[{"cron": "* * * * *"}])
async def dispatch_tracker_reminders() -> None:
    """Check all active trackers with reminders enabled and fire due ones."""
    now_utc = datetime.now(UTC)
    today_iso = now_utc.date().isoformat()

    # ── 1. Load all candidates ──────────────────────────────────────────────
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    Tracker,
                    User.telegram_id,
                    User.language,
                    UserProfile.preferred_language,
                    UserProfile.notification_language,
                    UserProfile.timezone,
                    UserProfile.timezone_source,
                )
                .join(User, Tracker.user_id == User.id)
                .outerjoin(UserProfile, UserProfile.user_id == User.id)
                .where(
                    Tracker.is_active.is_(True),
                    # JSONB boolean check: config->>'reminder_enabled' == 'true'
                    Tracker.config["reminder_enabled"].astext == "true",
                    Tracker.config["reminder_time"].astext.isnot(None),
                )
                .limit(500)
            )
        ).all()

        if not rows:
            return

        # ── 2. Filter to trackers whose reminder_time matches now (per-user tz) ──
        due: list[tuple] = []
        for row in rows:
            tracker, telegram_id, lang, pref_lang, notif_lang, tz_str, tz_src = row
            if not telegram_id:
                continue
            config = tracker.config or {}
            reminder_time: str | None = config.get("reminder_time")
            if not reminder_time:
                continue
            tz = _parse_tz(tz_str)
            now_local = now_utc.astimezone(tz)
            repeat_mins = config.get("reminder_repeat_minutes")
            if repeat_mins:
                # Repeat mode: fire whenever dedup expires AND we're past reminder_time
                if _is_past_reminder_time(reminder_time, now_local):
                    due.append(row)
            else:
                # One-shot: fire only at the exact minute
                if _matches_reminder_time(reminder_time, now_local):
                    due.append(row)

        if not due:
            return

        # ── 3. Dedup via Redis ──────────────────────────────────────────────
        from src.core.redis_client import redis  # lazy import to avoid circular

        filtered_due: list[tuple] = []
        for row in due:
            tracker = row[0]
            dedup_key = f"tracker_remind:{tracker.id}:{today_iso}"
            try:
                already = await redis.get(dedup_key)
            except Exception as exc:
                logger.warning(
                    "Redis dedup check failed for tracker %s, skipping: %s",
                    tracker.id, exc,
                )
                continue  # skip this tracker — don't double-fire on Redis failure
            if already:
                continue
            filtered_due.append(row)

        if not filtered_due:
            return

        # ── 4. Load today's entries for all candidate trackers in one query ──
        tracker_ids = [row[0].id for row in filtered_due]
        today_date = date.fromisoformat(today_iso)
        entry_rows = (
            await session.execute(
                select(TrackerEntry.tracker_id, TrackerEntry.value)
                .where(
                    TrackerEntry.tracker_id.in_(tracker_ids),
                    TrackerEntry.date == today_date,
                )
            )
        ).all()

        # Build: tracker_id → list of values logged today
        today_values: dict = {}
        for e_tracker_id, e_value in entry_rows:
            today_values.setdefault(str(e_tracker_id), []).append(e_value or 0)

        # ── 5. Send reminders for unlogged / goal-not-reached trackers ─────
        sent = 0
        for row in filtered_due:
            tracker, telegram_id, lang, pref_lang, notif_lang, tz_str, tz_src = row
            tid = str(tracker.id)
            config = tracker.config or {}
            value_mode = config.get("value_mode", "sum")
            goal = config.get("goal")
            logged_values = today_values.get(tid, [])

            # Decide whether to skip (already done)
            skip = False
            if value_mode == "boolean":
                skip = len(logged_values) > 0
            elif value_mode == "single":
                skip = len(logged_values) > 0
            else:  # sum
                if logged_values:
                    today_total = sum(logged_values)
                    if goal and today_total >= goal:
                        skip = True  # goal reached
                    # if no goal → always remind once (don't skip)

            if skip:
                # Goal reached — silence for the rest of the day (always 25h)
                dedup_key = f"tracker_remind:{tracker.id}:{today_iso}"
                try:
                    await redis.set(dedup_key, "1", ex=_DEDUP_TTL)
                except Exception as exc:
                    logger.warning("Redis set failed for dedup key %s: %s", dedup_key, exc)
                continue

            # Resolve locale for message language
            resolved = resolve_notification_locale(
                user_language=lang,
                preferred_language=pref_lang,
                notification_language=notif_lang,
                timezone=tz_str,
                timezone_source=tz_src,
                use_v2_read=False,
                prefer_user_on_desync=True,
            )
            message_lang = resolved.language

            emoji = tracker.emoji or "📊"
            text = _reminder_text(message_lang, emoji, tracker.name)

            # Append goal progress for sum mode
            if value_mode == "sum" and goal and logged_values:
                today_total = sum(logged_values)
                unit = config.get("unit", "")
                text += f"\n<i>{today_total} / {goal} {unit} so far</i>"

            try:
                await send_telegram_message(telegram_id, text)
                # Mark dedup — repeat mode uses shorter TTL so it fires again after interval
                dedup_key = f"tracker_remind:{tracker.id}:{today_iso}"
                repeat_mins = config.get("reminder_repeat_minutes")
                dedup_ttl = int(repeat_mins) * 60 if repeat_mins else _DEDUP_TTL
                try:
                    await redis.set(dedup_key, "1", ex=dedup_ttl)
                except Exception as exc:
                    logger.warning("Redis set failed after send for %s: %s", dedup_key, exc)
                sent += 1
                logger.info(
                    "Tracker reminder sent: tracker_id=%s user_id=%s telegram_id=%s",
                    tracker.id,
                    tracker.user_id,
                    telegram_id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send tracker reminder tracker_id=%s: %s",
                    tracker.id,
                    exc,
                )

    if sent:
        logger.info("dispatch_tracker_reminders: sent=%d", sent)
