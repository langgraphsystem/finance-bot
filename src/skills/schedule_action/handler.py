"""Schedule action skill — create Scheduled Intelligence Actions."""

import logging
import re
import uuid
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ActionStatus, OutputMode, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import fmt_date, fmt_time, register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SCHEDULE_ACTION_SYSTEM_PROMPT = """\
You help users schedule recurring intelligence actions.
Extract frequency, time, sources, and instruction for the summary/action.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""

_STRINGS = {
    "en": {
        "disabled": "Scheduled actions are not enabled yet.",
        "ask_instruction": "What should I include in this scheduled action?",
        "ask_schedule": "When should I run it? Please share frequency and time.",
        "ask_time": "What time should I use?",
        "time_in_past": "This time is already in the past. Please share a future time.",
        "confirm": (
            "✅ <b>Scheduled</b>\n"
            "• <b>{title}</b>\n"
            "• {schedule_desc}\n"
            "• Sources: {sources}\n"
            "• Next run: {next_run}"
        ),
    },
    "ru": {
        "disabled": "Запланированные действия пока не включены.",
        "ask_instruction": "Что включить в это запланированное действие?",
        "ask_schedule": "Когда запускать? Уточните частоту и время.",
        "ask_time": "На какое время поставить запуск?",
        "time_in_past": "Это время уже прошло. Укажите время в будущем.",
        "confirm": (
            "✅ <b>Запланировано</b>\n"
            "• <b>{title}</b>\n"
            "• {schedule_desc}\n"
            "• Источники: {sources}\n"
            "• Следующий запуск: {next_run}"
        ),
    },
    "es": {
        "disabled": "Las acciones programadas aun no estan habilitadas.",
        "ask_instruction": "Que debo incluir en esta accion programada?",
        "ask_schedule": "Cuando debo ejecutarla? Indica frecuencia y hora.",
        "ask_time": "Que hora debo usar?",
        "time_in_past": "Esa hora ya paso. Indica una hora futura.",
        "confirm": (
            "✅ <b>Programado</b>\n"
            "• <b>{title}</b>\n"
            "• {schedule_desc}\n"
            "• Fuentes: {sources}\n"
            "• Proxima ejecucion: {next_run}"
        ),
    },
}
register_strings("schedule_action", _STRINGS)

_SCHEDULE_LABELS = {
    "en": {
        "once": "once on {dt}",
        "daily": "daily at {time}",
        "weekly": "every {day} at {time}",
        "monthly": "monthly on day {day} at {time}",
        "weekdays": "weekdays at {time}",
    },
    "ru": {
        "once": "однократно {dt}",
        "daily": "ежедневно в {time}",
        "weekly": "каждый {day} в {time}",
        "monthly": "ежемесячно {day}-го в {time}",
        "weekdays": "по будням в {time}",
    },
    "es": {
        "once": "una vez el {dt}",
        "daily": "diariamente a las {time}",
        "weekly": "cada {day} a las {time}",
        "monthly": "mensualmente el dia {day} a las {time}",
        "weekdays": "dias laborables a las {time}",
    },
}

_WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
    "es": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"],
}

_SOURCE_LABELS = {
    "en": {
        "calendar": "calendar",
        "tasks": "tasks",
        "money_summary": "money",
        "email_highlights": "email",
        "outstanding": "outstanding",
    },
    "ru": {
        "calendar": "календарь",
        "tasks": "задачи",
        "money_summary": "финансы",
        "email_highlights": "почта",
        "outstanding": "неоплаченные",
    },
    "es": {
        "calendar": "calendario",
        "tasks": "tareas",
        "money_summary": "finanzas",
        "email_highlights": "correo",
        "outstanding": "pendientes",
    },
}

_SOURCE_MAP = {
    "calendar": "calendar",
    "schedule": "calendar",
    "event": "calendar",
    "events": "calendar",
    "tasks": "tasks",
    "task": "tasks",
    "todo": "tasks",
    "money": "money_summary",
    "finance": "money_summary",
    "finances": "money_summary",
    "budget": "money_summary",
    "email": "email_highlights",
    "mail": "email_highlights",
    "inbox": "email_highlights",
    "outstanding": "outstanding",
    "unpaid": "outstanding",
}

_WEEKDAY_MAP = {
    "monday": 0,
    "mon": 0,
    "понедельник": 0,
    "пн": 0,
    "lunes": 0,
    "tuesday": 1,
    "tue": 1,
    "вторник": 1,
    "вт": 1,
    "martes": 1,
    "wednesday": 2,
    "wed": 2,
    "среда": 2,
    "ср": 2,
    "miercoles": 2,
    "thursday": 3,
    "thu": 3,
    "четверг": 3,
    "чт": 3,
    "jueves": 3,
    "friday": 4,
    "fri": 4,
    "пятница": 4,
    "пт": 4,
    "viernes": 4,
    "saturday": 5,
    "sat": 5,
    "суббота": 5,
    "сб": 5,
    "sabado": 5,
    "sunday": 6,
    "sun": 6,
    "воскресенье": 6,
    "вс": 6,
    "domingo": 6,
}


def _t(key: str, language: str, **kwargs: str) -> str:
    strings = _STRINGS.get(language, _STRINGS["en"])
    return strings[key].format(**kwargs)


def _parse_schedule_kind(intent_data: dict[str, Any], text: str) -> ScheduleKind | None:
    raw = (intent_data.get("schedule_frequency") or "").strip().lower()
    if raw:
        normalized = {
            "one_time": "once",
            "one-time": "once",
            "everyday": "daily",
        }.get(raw, raw)
        try:
            return ScheduleKind(normalized)
        except ValueError:
            pass

    text_lower = text.lower()
    if any(word in text_lower for word in ("weekdays", "будни", "laborables")):
        return ScheduleKind.weekdays
    if any(word in text_lower for word in ("daily", "каждый день", "ежедневно", "diario")):
        return ScheduleKind.daily
    if any(word in text_lower for word in ("weekly", "каждую неделю", "еженедельно", "semanal")):
        return ScheduleKind.weekly
    if any(word in text_lower for word in ("monthly", "каждый месяц", "ежемесячно", "mensual")):
        return ScheduleKind.monthly
    if any(word in text_lower for word in ("once", "one time", "разово", "один раз")):
        return ScheduleKind.once
    return None


def _parse_time_parts(raw_time: str | None) -> tuple[int, int] | None:
    if not raw_time:
        return None
    value = re.sub(r"\s+", " ", raw_time.strip().lower()).replace(".", ":")
    if not value:
        return None

    formats = ("%H:%M", "%H", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p")
    for fmt in formats:
        try:
            dt = datetime.strptime(value.upper() if "%p" in fmt else value, fmt)  # noqa: UP017
            return dt.hour, dt.minute
        except ValueError:
            continue

    m = re.fullmatch(r"(\d{1,2})(\d{2})\s*([ap]m)", value)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        suffix = m.group(3)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        return hour, minute

    return None


def _parse_datetime(raw: str, timezone: str) -> datetime | None:
    try:
        tz = ZoneInfo(timezone)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, TypeError, KeyError):
        return None


def _parse_once_run_at(intent_data: dict[str, Any], timezone: str) -> datetime | None:
    raw_dt = intent_data.get("task_deadline") or intent_data.get("event_datetime")
    if raw_dt:
        parsed = _parse_datetime(raw_dt, timezone)
        if parsed:
            return parsed

    raw_date = intent_data.get("date")
    time_parts = _parse_time_parts(intent_data.get("schedule_time"))
    if raw_date:
        try:
            d = date.fromisoformat(raw_date)
            tz = ZoneInfo(timezone)
            hour, minute = time_parts or (9, 0)
            return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)
        except (TypeError, ValueError, KeyError):
            return None

    if time_parts:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        hour, minute = time_parts
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return None


def _parse_weekday(intent_data: dict[str, Any], text: str, now: datetime) -> int:
    raw = (intent_data.get("schedule_day_of_week") or "").strip().lower()
    if raw in _WEEKDAY_MAP:
        return _WEEKDAY_MAP[raw]

    text_lower = text.lower()
    for key, day in _WEEKDAY_MAP.items():
        if key in text_lower:
            return day
    return now.weekday()


def _compute_recurring_next_run(
    schedule_kind: ScheduleKind,
    now: datetime,
    hour: int,
    minute: int,
    weekday: int,
    day_of_month: int,
) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if schedule_kind == ScheduleKind.daily:
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if schedule_kind == ScheduleKind.weekdays:
        if candidate <= now:
            candidate += timedelta(days=1)
        while candidate.weekday() > 4:
            candidate += timedelta(days=1)
        return candidate

    if schedule_kind == ScheduleKind.weekly:
        days_ahead = (weekday - now.weekday()) % 7
        candidate = now + timedelta(days=days_ahead)
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    if schedule_kind == ScheduleKind.monthly:
        safe_day = min(day_of_month, monthrange(now.year, now.month)[1])
        candidate = now.replace(day=safe_day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            month = 1 if now.month == 12 else now.month + 1
            year = now.year + 1 if month == 1 else now.year
            safe_day = min(day_of_month, monthrange(year, month)[1])
            candidate = candidate.replace(year=year, month=month, day=safe_day)
        return candidate

    return candidate


def _normalize_sources(raw_sources: Any, text: str) -> list[str]:
    sources: list[str] = []
    candidates: list[str] = []

    if isinstance(raw_sources, list):
        candidates.extend(str(item).strip().lower() for item in raw_sources)
    elif isinstance(raw_sources, str):
        candidates.extend(part.strip().lower() for part in raw_sources.split(","))

    text_lower = text.lower()
    if "calendar" in text_lower or "календар" in text_lower or "calendario" in text_lower:
        candidates.append("calendar")
    if "task" in text_lower or "задач" in text_lower or "tarea" in text_lower:
        candidates.append("tasks")
    if "money" in text_lower or "финанс" in text_lower or "finanz" in text_lower:
        candidates.append("money")
    if "email" in text_lower or "почт" in text_lower or "correo" in text_lower:
        candidates.append("email")
    if "unpaid" in text_lower or "неопла" in text_lower or "pendiente" in text_lower:
        candidates.append("outstanding")

    for candidate in candidates:
        mapped = _SOURCE_MAP.get(candidate)
        if mapped and mapped not in sources:
            sources.append(mapped)

    return sources or ["calendar", "tasks"]


def _parse_output_mode(raw: str | None) -> OutputMode:
    if not raw:
        return OutputMode.compact
    value = raw.strip().lower().replace("-", "_")
    if value == "decision_ready":
        return OutputMode.decision_ready
    return OutputMode.compact


def _parse_end_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        try:
            d = date.fromisoformat(raw)
            return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
        except ValueError:
            return None


def _schedule_description(
    schedule_kind: ScheduleKind,
    next_run_at: datetime,
    timezone: str,
    language: str,
    weekday: int,
    day_of_month: int,
) -> str:
    labels = _SCHEDULE_LABELS.get(language, _SCHEDULE_LABELS["en"])
    local_next = next_run_at.astimezone(ZoneInfo(timezone))

    if schedule_kind == ScheduleKind.once:
        return labels["once"].format(dt=fmt_date(local_next, language, timezone=timezone))
    if schedule_kind == ScheduleKind.daily:
        return labels["daily"].format(time=fmt_time(local_next, language, timezone=timezone))
    if schedule_kind == ScheduleKind.weekdays:
        return labels["weekdays"].format(time=fmt_time(local_next, language, timezone=timezone))
    if schedule_kind == ScheduleKind.weekly:
        day = _WEEKDAYS.get(language, _WEEKDAYS["en"])[weekday]
        return labels["weekly"].format(
            day=day,
            time=fmt_time(local_next, language, timezone=timezone),
        )
    return labels["monthly"].format(
        day=day_of_month,
        time=fmt_time(local_next, language, timezone=timezone),
    )


class ScheduleActionSkill:
    name = "schedule_action"
    intents = ["schedule_action"]
    model = "gpt-5.2"

    @observe(name="schedule_action")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        language = context.language or "en"
        if not settings.ff_scheduled_actions:
            return SkillResult(response_text=_t("disabled", language))

        instruction = (
            intent_data.get("schedule_instruction")
            or intent_data.get("description")
            or message.text
            or ""
        ).strip()
        if not instruction:
            return SkillResult(response_text=_t("ask_instruction", language))

        schedule_kind = _parse_schedule_kind(intent_data, message.text or "")
        if schedule_kind is None:
            return SkillResult(response_text=_t("ask_schedule", language))

        timezone = context.timezone or "America/New_York"
        now = datetime.now(ZoneInfo(timezone))
        weekday = now.weekday()
        day_of_month = now.day
        schedule_config: dict[str, Any] = {}

        if schedule_kind == ScheduleKind.once:
            next_run_at = _parse_once_run_at(intent_data, timezone)
            if not next_run_at:
                return SkillResult(response_text=_t("ask_schedule", language))
            next_run_at = next_run_at.astimezone(ZoneInfo(timezone))
            schedule_config["run_at"] = next_run_at.isoformat()
            schedule_config["time"] = next_run_at.strftime("%H:%M")
        else:
            time_parts = _parse_time_parts(intent_data.get("schedule_time"))
            if not time_parts:
                fallback = _parse_once_run_at(intent_data, timezone)
                if fallback:
                    local = fallback.astimezone(ZoneInfo(timezone))
                    time_parts = (local.hour, local.minute)
            if not time_parts:
                return SkillResult(response_text=_t("ask_time", language))

            hour, minute = time_parts
            weekday = _parse_weekday(intent_data, message.text or "", now)
            try:
                day_of_month = int(intent_data.get("schedule_day_of_month") or now.day)
            except (TypeError, ValueError):
                day_of_month = now.day

            schedule_config["time"] = f"{hour:02d}:{minute:02d}"
            if schedule_kind == ScheduleKind.weekly:
                schedule_config["days"] = [weekday]
            if schedule_kind == ScheduleKind.monthly:
                schedule_config["day_of_month"] = day_of_month

            next_run_at = _compute_recurring_next_run(
                schedule_kind=schedule_kind,
                now=now,
                hour=hour,
                minute=minute,
                weekday=weekday,
                day_of_month=day_of_month,
            )

        if next_run_at <= now:
            return SkillResult(response_text=_t("time_in_past", language))

        output_mode = _parse_output_mode(intent_data.get("schedule_output_mode"))
        sources = _normalize_sources(intent_data.get("schedule_sources"), message.text or "")
        title = (
            intent_data.get("task_title") or intent_data.get("managed_action_title") or ""
        ).strip()
        if not title:
            title = instruction[:70].strip()

        action = ScheduledAction(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=title,
            instruction=instruction,
            action_kind="digest",
            schedule_kind=schedule_kind,
            schedule_config=schedule_config,
            sources=sources,
            output_mode=output_mode,
            timezone=timezone,
            language=language,
            status=ActionStatus.active,
            next_run_at=next_run_at,
            end_at=_parse_end_at(intent_data.get("schedule_end_date")),
            max_runs=intent_data.get("schedule_max_runs"),
        )

        await save_scheduled_action(action)
        intent_data["_record_id"] = str(action.id)
        intent_data["_record_table"] = "scheduled_actions"

        source_labels = _SOURCE_LABELS.get(language, _SOURCE_LABELS["en"])
        source_text = ", ".join(source_labels.get(source, source) for source in sources)
        schedule_desc = _schedule_description(
            schedule_kind=schedule_kind,
            next_run_at=next_run_at,
            timezone=timezone,
            language=language,
            weekday=weekday,
            day_of_month=day_of_month,
        )
        next_run = fmt_date(next_run_at, language, timezone=timezone)
        return SkillResult(
            response_text=_t(
                "confirm",
                language,
                title=title,
                schedule_desc=schedule_desc,
                sources=source_text,
                next_run=next_run,
            ),
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SCHEDULE_ACTION_SYSTEM_PROMPT.format(language=context.language or "en")


async def save_scheduled_action(action: ScheduledAction) -> None:
    async with async_session() as session:
        session.add(action)
        await session.commit()


skill = ScheduleActionSkill()
