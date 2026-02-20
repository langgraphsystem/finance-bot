"""Set reminder skill — create a task with optional recurrence and context-aware time extraction."""

import json as _json
import logging
import uuid
from datetime import date, datetime, timedelta
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
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SET_REMINDER_SYSTEM_PROMPT = """\
You help users set reminders. Extract the reminder text, time, and recurrence.
Respond in the user's preferred language: {language}.
If no preference is set, detect and match the language of their message."""

CONTEXT_EXTRACTION_PROMPT = """\
You extract reminder details from a conversation.
The user wants to set a reminder. Extract:
1. reminder_title: what to remind about (short, 3-10 words)
2. reminder_times: list of objects {{"time": "HH:MM", "label": "short description"}}
3. recurrence: "daily", "weekly", "monthly", or null
4. end_date: "YYYY-MM-DD" or null

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
        "with_time": "🔔 Reminder set for {time}: {title}",
        "no_time": "🔔 Reminder saved: {title} (no specific time)",
        "with_time_recurring": "🔔 {recurrence} reminder set for {time}: {title}",
        "multi_set": "🔔 Reminders set",
    },
    "ru": {
        "empty": "О чём вам напомнить?",
        "with_time": "🔔 Напоминание установлено на {time}: {title}",
        "no_time": "🔔 Напоминание сохранено: {title} (без конкретного времени)",
        "with_time_recurring": "🔔 {recurrence} напоминание на {time}: {title}",
        "multi_set": "🔔 Напоминания установлены",
    },
}

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
        model="gpt-5.2",
        max_tokens=512,
        response_format={"type": "json_object"},
        **PromptAdapter.for_openai(system, [{"role": "user", "content": user_prompt}]),
    )

    return _json.loads(response.choices[0].message.content)


class SetReminderSkill:
    name = "set_reminder"
    intents = ["set_reminder"]
    model = "gpt-5.2"

    @observe(name="set_reminder")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        title = (
            intent_data.get("task_title") or intent_data.get("description") or message.text or ""
        )
        title = title.strip()

        if not title:
            return SkillResult(response_text=_t("empty", lang))

        reminder_time = _parse_reminder_time(intent_data, context.timezone)
        recurrence_str = intent_data.get("reminder_recurrence")
        end_date_str = intent_data.get("reminder_end_date")

        # Context-aware extraction: if no time was parsed, use dialog context + LLM
        extracted_times: list[dict] = []
        if not reminder_time:
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

        recurrence = _parse_recurrence(recurrence_str)
        recurrence_end = _parse_end_date(end_date_str)

        # Multiple reminders (e.g., suhur at 5:08 + iftar at 17:28)
        if len(extracted_times) > 1:
            return await _create_multiple_reminders(
                extracted_times, title, recurrence, recurrence_end, context, message, lang
            )

        # Single extracted time
        if extracted_times:
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
        return _build_response(task, lang, recurrence)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SET_REMINDER_SYSTEM_PROMPT.format(language=context.language or "en")


def _build_response(
    task: Task, lang: str, recurrence: ReminderRecurrence
) -> SkillResult:
    """Build response text for a single reminder."""
    if task.reminder_at:
        time_str = task.reminder_at.strftime("%I:%M %p").lstrip("0")
        if recurrence != ReminderRecurrence.none:
            labels = _RECURRENCE_LABELS.get(lang, _RECURRENCE_LABELS["en"])
            rec_label = labels.get(recurrence.value, recurrence.value)
            return SkillResult(
                response_text=_t(
                    "with_time_recurring", lang,
                    time=time_str, title=task.title, recurrence=rec_label,
                )
            )
        return SkillResult(
            response_text=_t("with_time", lang, time=time_str, title=task.title)
        )
    return SkillResult(response_text=_t("no_time", lang, title=task.title))


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
    lines: list[str] = []
    for label, rt in created:
        time_str = rt.strftime("%I:%M %p").lstrip("0") if rt else "?"
        lines.append(f"  • {label}: {time_str}")

    recurrence_note = ""
    if recurrence != ReminderRecurrence.none:
        labels = _RECURRENCE_LABELS.get(lang, _RECURRENCE_LABELS["en"])
        recurrence_note = f" ({labels.get(recurrence.value, recurrence.value)})"

    header = _t("multi_set", lang)
    text = f"{header}{recurrence_note}:\n" + "\n".join(lines)
    return SkillResult(response_text=text)


async def save_reminder(task: Task) -> None:
    """Persist a reminder task to the database."""
    async with async_session() as session:
        session.add(task)
        await session.commit()


skill = SetReminderSkill()
