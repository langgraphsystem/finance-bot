"""Set reminder skill — create a task with optional recurrence and context-aware time extraction."""

import json as _json
import logging
import re
import uuid
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import openai_client
from src.core.llm.prompts import PromptAdapter
from src.core.models.enums import ReminderRecurrence, TaskPriority, TaskStatus
from src.core.models.task import Task
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Bare trigger words that shouldn't be used as a reminder title
_REMINDER_TRIGGERS = {
    "напомни", "напоминай", "напоминание", "напомните",
    "remind", "remind me", "reminder", "set reminder", "set a reminder",
    "recuérdame", "recordatorio",
}

# Regex patterns for relative time expressions (RU/EN/ES)
_RELATIVE_TIME_RE = re.compile(
    r"^(?:напомни(?:те)?|remind\s+me|recuérdame)\s+"  # trigger word
    r"(?:через\s+\d+\s+(?:минут\w*|час\w*|секунд\w*)"  # RU: через N минут/часов
    r"|in\s+\d+\s+(?:minute|hour|second)s?"  # EN: in N minutes/hours
    r"|en\s+\d+\s+(?:minuto|hora|segundo)s?)"  # ES: en N minutos/horas
    r"\s+(.+)",  # capture the action part
    re.IGNORECASE,
)

# Standalone relative time (used as task_title by the LLM)
_RELATIVE_TIME_ONLY_RE = re.compile(
    r"^(?:через\s+\d+\s+(?:минут\w*|час\w*|секунд\w*)"
    r"|in\s+\d+\s+(?:minute|hour|second)s?"
    r"|en\s+\d+\s+(?:minuto|hora|segundo)s?)$",
    re.IGNORECASE,
)


def _extract_action_from_relative_time(message_text: str) -> str | None:
    """Extract the action part from a relative-time reminder message.

    E.g., "напомни через 10 минут проверить духовку" → "проверить духовку"
    """
    m = _RELATIVE_TIME_RE.match(message_text.strip())
    return m.group(1).strip() if m else None

_TITLE_STRIP_RE = re.compile(
    r"^(?:(?:напомни(?:те)?|remind\s+me|recuérdame)"
    r"\s+(?:about\s+(?:this|that)|об\s+этом|sobre\s+esto)"
    r"(?:\s+(?:tomorrow|завтра|mañana))?"
    r"(?:\s+(?:at|в|a)\s+\S+)?)"
    r"\s*",
    re.IGNORECASE,
)

_TITLE_PREFIX_RE = re.compile(
    r"^(?:напомни(?:те)?|remind\s+me|recuérdame)\s+",
    re.IGNORECASE,
)


def _clean_reminder_title(text: str) -> str:
    """Strip trigger words and time references from a reminder message."""
    # Try stripping "remind me about this tomorrow at 5pm" → ""
    cleaned = _TITLE_STRIP_RE.sub("", text).strip()
    if cleaned:
        return cleaned
    # Try stripping just "remind me " prefix → rest
    cleaned = _TITLE_PREFIX_RE.sub("", text).strip()
    if cleaned:
        return cleaned
    return text


SET_REMINDER_SYSTEM_PROMPT = """\
You help users set reminders. Extract the reminder text, time, and recurrence.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""

CONTEXT_EXTRACTION_PROMPT = """\
You extract reminder details from a conversation.
The user wants to set a reminder. Extract:
1. reminder_title: what to remind about (short, 3-10 words). \
If the user says "remind me about this/that", look at previous messages \
to find what "this/that" refers to.
2. reminder_times: list of objects {{"time": "HH:MM", "label": "short description"}}
3. recurrence: "daily", "weekly", "monthly", or null
4. end_date: "YYYY-MM-DD" or null

CRITICAL RULES:
- Only include times that were EXPLICITLY mentioned by the user.
- If the user says "tomorrow" without a specific time, return reminder_times: [].
- NEVER invent a default time (like 09:00). If no time was stated, \
return an empty list.
- If the user says "remind me about this", extract the subject from \
the PREVIOUS message in the conversation, not from the current one.

Today: {today}. User timezone: {timezone}.

If the conversation history mentions specific times (e.g., "suhur at 5:08 AM, \
iftar at 5:28 PM"), extract those times even if the current message just says \
"set reminders" or "exactly by time".

Use 24-hour format for times (e.g., "05:08", "17:28").
Respond with valid JSON only. No markdown."""

# Language-aware response strings
_STRINGS = {
    "en": {
        "empty": "What should I remind you about?",
        "ask_time": (
            "Got it — <b>{title}</b>\n\n"
            "What time should I remind you?"
        ),
        "ask_both": (
            "I'd like to help! Could you clarify:\n"
            "• What should I remind you about?\n"
            "• When?"
        ),
        "with_time": "\U0001f514 Reminder set for {time}: {title}",
        "no_time": "\U0001f514 Reminder saved: {title} (no specific time)",
        "with_time_recurring": "\U0001f514 {recurrence} reminder set for {time}: {title}",
        "multi_set": "\U0001f514 Reminders set",
    },
    "ru": {
        "empty": "О чём вам напомнить?",
        "ask_time": (
            "Понял — <b>{title}</b>\n\n"
            "На какое время поставить напоминание?"
        ),
        "ask_both": (
            "Хочу помочь! Уточните:\n"
            "• О чём напомнить?\n"
            "• Когда?"
        ),
        "with_time": "\U0001f514 Напоминание на {time}: {title}",
        "no_time": "\U0001f514 Напоминание сохранено: {title} (без времени)",
        "with_time_recurring": "\U0001f514 {recurrence} напоминание на {time}: {title}",
        "multi_set": "\U0001f514 Напоминания установлены",
    },
    "es": {
        "empty": "¿De qué quieres que te recuerde?",
        "ask_time": (
            "Entendido — <b>{title}</b>\n\n"
            "¿A qué hora te lo recuerdo?"
        ),
        "ask_both": (
            "¡Quiero ayudar! Aclara:\n"
            "• ¿De qué recordarte?\n"
            "• ¿Cuándo?"
        ),
        "with_time": "\U0001f514 Recordatorio a las {time}: {title}",
        "no_time": "\U0001f514 Recordatorio guardado: {title} (sin hora)",
        "with_time_recurring": "\U0001f514 Recordatorio {recurrence} a las {time}: {title}",
        "multi_set": "\U0001f514 Recordatorios configurados",
    },
}
register_strings("set_reminder", _STRINGS)

_RECURRENCE_LABELS = {
    "en": {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"},
    "ru": {"daily": "Ежедневное", "weekly": "Еженедельное", "monthly": "Ежемесячное"},
}


def _t(key: str, language: str, **kwargs: str) -> str:
    """Get a translated string, falling back to English."""
    strings = _STRINGS.get(language, _STRINGS["en"])
    return strings[key].format(**kwargs)


def _parse_reminder_time(intent_data: dict[str, Any], timezone: str) -> datetime | None:
    """Parse reminder time from intent_data fields."""
    raw = (
        intent_data.get("task_deadline")
        or intent_data.get("event_datetime")
        or intent_data.get("date")
    )
    if not raw:
        return None
    try:
        tz = ZoneInfo(timezone)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, KeyError):
        return None


def _parse_recurrence(raw: str | None) -> ReminderRecurrence:
    """Parse recurrence string to enum."""
    if not raw:
        return ReminderRecurrence.none
    mapping = {
        "daily": ReminderRecurrence.daily,
        "weekly": ReminderRecurrence.weekly,
        "monthly": ReminderRecurrence.monthly,
    }
    return mapping.get(raw.lower(), ReminderRecurrence.none)


def _parse_time_str(time_str: str, timezone: str) -> datetime | None:
    """Parse 'HH:MM' into a timezone-aware datetime for today or tomorrow."""
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        hour, minute = map(int, time_str.split(":"))
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt
    except (ValueError, KeyError):
        return None


def _parse_end_date(raw: str | None) -> datetime | None:
    """Parse YYYY-MM-DD to end-of-day datetime in UTC."""
    if not raw:
        return None
    try:
        from datetime import UTC

        d = date.fromisoformat(raw)
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _ru_minutes(n: int) -> str:
    """Russian plural for 'минута'."""
    if 11 <= n % 100 <= 19:
        return "минут"
    last = n % 10
    if last == 1:
        return "минуту"
    if 2 <= last <= 4:
        return "минуты"
    return "минут"


def _ru_hours(n: int) -> str:
    """Russian plural for 'час'."""
    if 11 <= n % 100 <= 19:
        return "часов"
    last = n % 10
    if last == 1:
        return "час"
    if 2 <= last <= 4:
        return "часа"
    return "часов"


def _format_relative_en(total_minutes: int) -> str:
    """English relative time: 'in 15 minutes'."""
    if total_minutes < 60:
        unit = "minute" if total_minutes == 1 else "minutes"
        return f"in {total_minutes} {unit}"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    hour_unit = "hour" if hours == 1 else "hours"
    if minutes == 0:
        return f"in {hours} {hour_unit}"
    minute_unit = "minute" if minutes == 1 else "minutes"
    return f"in {hours} {hour_unit} {minutes} {minute_unit}"


def _format_relative_ru(total_minutes: int) -> str:
    """Russian relative time: 'через 15 минут'."""
    if total_minutes < 60:
        return f"через {total_minutes} {_ru_minutes(total_minutes)}"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if minutes == 0:
        return f"через {hours} {_ru_hours(hours)}"
    return f"через {hours} {_ru_hours(hours)} {minutes} {_ru_minutes(minutes)}"


def _format_confirmation_time(
    reminder_at: datetime, timezone: str, lang: str = "en",
) -> tuple[str, str]:
    """Format wall-clock time and a localized human-readable relative delta."""
    tz = ZoneInfo(timezone)
    now_local = datetime.now(tz)
    reminder_local = reminder_at.astimezone(tz)
    total_seconds = max((reminder_local - now_local).total_seconds(), 0)
    total_minutes = max(1, ceil(total_seconds / 60))

    if lang == "ru":
        relative = _format_relative_ru(total_minutes)
    else:
        relative = _format_relative_en(total_minutes)

    if lang == "ru":
        time_str = reminder_local.strftime("%H:%M")
    else:
        time_str = reminder_local.strftime("%I:%M %p").lstrip("0")

    return time_str, relative


_CONFIRMATION_HEADER = {
    "en": "⏰ <b>Reminder set</b>",
    "ru": "⏰ <b>Напоминание установлено</b>",
}

_RECURRENCE_LINE = {
    "en": {
        "daily": "🔄 Repeats daily",
        "weekly": "🔄 Repeats weekly",
        "monthly": "🔄 Repeats monthly",
    },
    "ru": {
        "daily": "🔄 Ежедневно",
        "weekly": "🔄 Еженедельно",
        "monthly": "🔄 Ежемесячно",
    },
}


def _build_scheduled_confirmation(
    task_title: str,
    reminder_at: datetime,
    timezone: str,
    lang: str = "en",
    recurrence: ReminderRecurrence = ReminderRecurrence.none,
) -> str:
    """Build a nicely formatted reminder confirmation (Telegram HTML)."""
    time_str, relative = _format_confirmation_time(reminder_at, timezone, lang)
    header = _CONFIRMATION_HEADER.get(lang, _CONFIRMATION_HEADER["en"])

    lines = [header, "", f"📝 {task_title}", f"🕐 {time_str} ({relative})"]

    if recurrence != ReminderRecurrence.none:
        rec_labels = _RECURRENCE_LINE.get(lang, _RECURRENCE_LINE["en"])
        rec_line = rec_labels.get(recurrence.value)
        if rec_line:
            lines.append(rec_line)

    return "\n".join(lines)


async def _extract_from_context(
    message_text: str,
    assembled_messages: list[dict[str, str]],
    timezone: str,
) -> dict:
    """Use GPT-5.2 to extract reminder details from conversation context."""
    client = openai_client()

    context_text = "\n".join(
        f"{m['role'].title()}: {m['content'][:500]}"
        for m in assembled_messages[-6:]
        if m.get("content")
    )

    user_prompt = (
        f"Conversation:\n{context_text}\n\n"
        f"Current message: {message_text}\n\n"
        "Extract reminder details as JSON."
    )

    system = CONTEXT_EXTRACTION_PROMPT.format(
        today=date.today().isoformat(),
        timezone=timezone,
    )

    response = await client.chat.completions.create(
        model="gpt-5.4-2026-03-05",
        max_completion_tokens=512,
        response_format={"type": "json_object"},
        **PromptAdapter.for_openai(system, [{"role": "user", "content": user_prompt}]),
    )

    return _json.loads(response.choices[0].message.content)


class SetReminderSkill:
    name = "set_reminder"
    intents = ["set_reminder"]
    model = "gpt-5.4-2026-03-05"

    @observe(name="set_reminder")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        title = intent_data.get("task_title") or intent_data.get("description") or ""
        if not title:
            # Fallback to message text, but clean it up
            fallback = (message.text or "").strip()
            if fallback.lower() not in _REMINDER_TRIGGERS:
                title = _clean_reminder_title(fallback)
        title = title.strip()

        reminder_time = _parse_reminder_time(intent_data, context.timezone)
        recurrence_str = intent_data.get("reminder_recurrence")
        end_date_str = intent_data.get("reminder_end_date")

        # Always try context extraction to enrich title + time from dialog
        extracted_times: list[dict] = []
        assembled = intent_data.get("_assembled")
        if assembled and hasattr(assembled, "messages") and assembled.messages:
            try:
                extracted = await _extract_from_context(
                    message.text or title,
                    assembled.messages,
                    context.timezone,
                )
                extracted_times = extracted.get("reminder_times") or []
                if not recurrence_str:
                    recurrence_str = extracted.get("recurrence")
                if not end_date_str:
                    end_date_str = extracted.get("end_date")
                if extracted.get("reminder_title"):
                    title = extracted["reminder_title"]
            except Exception as e:
                logger.warning("Context extraction failed: %s", e)

        # Fix: if any LLM put the relative time expression as title
        if title and _RELATIVE_TIME_ONLY_RE.match(title):
            action = _extract_action_from_relative_time(message.text or "")
            if action:
                title = action

        # --- Clarification: ask user if info is missing ---
        if not title and not reminder_time and not extracted_times:
            return SkillResult(response_text=_t("ask_both", lang))
        if not title:
            return SkillResult(response_text=_t("empty", lang))
        if not reminder_time and not extracted_times:
            return SkillResult(
                response_text=_t("ask_time", lang, title=title),
            )

        recurrence = _parse_recurrence(recurrence_str)
        recurrence_end = _parse_end_date(end_date_str)

        # Multiple reminders (e.g., suhur at 5:08 + iftar at 17:28)
        if len(extracted_times) > 1:
            return await _create_multiple_reminders(
                extracted_times, title, recurrence, recurrence_end,
                context, message, lang,
            )

        # Single extracted time
        if extracted_times and not reminder_time:
            t = extracted_times[0]
            reminder_time = _parse_time_str(t["time"], context.timezone)
            title = t.get("label") or title

        task = Task(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=title,
            status=TaskStatus.pending,
            priority=TaskPriority.medium,
            due_at=reminder_time,
            reminder_at=reminder_time,
            recurrence=recurrence,
            recurrence_end_at=recurrence_end,
            original_reminder_time=(
                reminder_time.strftime("%H:%M") if reminder_time else None
            ),
            domain="tasks",
            source_message_id=message.id,
        )

        await save_reminder(task)
        return _build_response(task, lang, recurrence, context.timezone)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SET_REMINDER_SYSTEM_PROMPT.format(language=context.language or "en")


def _build_response(
    task: Task, lang: str, recurrence: ReminderRecurrence,
    timezone: str = "America/New_York",
) -> SkillResult:
    """Build response text for a single reminder."""
    if task.reminder_at:
        return SkillResult(
            response_text=_build_scheduled_confirmation(
                task.title, task.reminder_at, timezone, lang, recurrence,
            )
        )
    header = _CONFIRMATION_HEADER.get(lang, _CONFIRMATION_HEADER["en"])
    no_time_hint = "⏳ Без указания времени" if lang == "ru" else "⏳ No specific time"
    return SkillResult(response_text=f"{header}\n\n📝 {task.title}\n{no_time_hint}")


async def _create_multiple_reminders(
    times: list[dict],
    base_title: str,
    recurrence: ReminderRecurrence,
    recurrence_end: datetime | None,
    context: SessionContext,
    message: IncomingMessage,
    lang: str,
) -> SkillResult:
    """Create multiple reminder tasks (e.g., suhur + iftar)."""
    created: list[tuple[str, datetime | None]] = []
    for t in times:
        reminder_time = _parse_time_str(t["time"], context.timezone)
        label = t.get("label") or base_title

        task = Task(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=label,
            status=TaskStatus.pending,
            priority=TaskPriority.medium,
            due_at=reminder_time,
            reminder_at=reminder_time,
            recurrence=recurrence,
            recurrence_end_at=recurrence_end,
            original_reminder_time=(
                reminder_time.strftime("%H:%M") if reminder_time else None
            ),
            domain="tasks",
            source_message_id=message.id,
        )
        await save_reminder(task)
        created.append((label, reminder_time))

    # Build response
    from src.skills._i18n import fmt_time

    multi_header = {
        "en": "⏰ <b>Reminders set</b>",
        "ru": "⏰ <b>Напоминания установлены</b>",
    }
    header = multi_header.get(lang, multi_header["en"])
    lines: list[str] = [header, ""]
    for label, rt in created:
        time_str = fmt_time(rt, lang, timezone=context.timezone) if rt else "?"
        lines.append(f"📝 {label} — {time_str}")

    if recurrence != ReminderRecurrence.none:
        rec_labels = _RECURRENCE_LINE.get(lang, _RECURRENCE_LINE["en"])
        rec_line = rec_labels.get(recurrence.value)
        if rec_line:
            lines.append(rec_line)

    return SkillResult(response_text="\n".join(lines))


async def save_reminder(task: Task) -> None:
    """Persist a reminder task to the database."""
    async with async_session() as session:
        session.add(task)
        await session.commit()


skill = SetReminderSkill()
