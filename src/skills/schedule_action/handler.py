"""Schedule action skill — create Scheduled Intelligence Actions."""

import logging
import re
import uuid
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ActionStatus, OutputMode, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.core.scheduled_actions.config import ScheduleConfig
from src.core.scheduled_actions.engine import compute_next_run, is_valid_cron_expression
from src.core.scheduled_actions.i18n import (
    SCHEDULE_LABELS,
    SOURCE_LABELS,
    WEEKDAY_NAMES,
)
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
        "ask_cron": "Please share a valid cron expression (minimum interval is 5 minutes).",
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
        "ask_cron": "Укажите корректный cron (минимальный интервал — 5 минут).",
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
        "disabled": "Las acciones programadas aún no están habilitadas.",
        "ask_instruction": "¿Qué debo incluir en esta acción programada?",
        "ask_schedule": "¿Cuándo debo ejecutarla? Indica frecuencia y hora.",
        "ask_time": "¿Qué hora debo usar?",
        "ask_cron": "Indica una expresión cron válida (intervalo mínimo: 5 minutos).",
        "time_in_past": "Esa hora ya pasó. Indica una hora futura.",
        "confirm": (
            "✅ <b>Programado</b>\n"
            "• <b>{title}</b>\n"
            "• {schedule_desc}\n"
            "• Fuentes: {sources}\n"
            "• Próxima ejecución: {next_run}"
        ),
    },
}
register_strings("schedule_action", _STRINGS)

_SCHEDULE_LABELS = SCHEDULE_LABELS
_WEEKDAYS = WEEKDAY_NAMES
_SOURCE_LABELS = SOURCE_LABELS

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
    "miércoles": 2,
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
    "sábado": 5,
    "sunday": 6,
    "sun": 6,
    "воскресенье": 6,
    "вс": 6,
    "domingo": 6,
}

_OUTCOME_HINTS = (
    "until done",
    "till done",
    "until completed",
    "until complete",
    "until paid",
    "до выполнения",
    "до завершения",
    "пока не выполн",
    "пока не оплачен",
    "hasta completar",
    "hasta que se complete",
    "hasta que se pague",
)
_TASK_HINTS = (
    "task",
    "tasks",
    "todo",
    "задач",
    "дел",
    "tarea",
    "tareas",
)
_INVOICE_HINTS = (
    "invoice",
    "invoices",
    "paid",
    "payment",
    "bill",
    "оплат",
    "счет",
    "инвойс",
    "factura",
    "pago",
)
_OUTCOME_CONDITIONS = {
    "empty": "empty",
    "task_completed": "task_completed",
    "tasks_completed": "task_completed",
    "tasks_empty": "task_completed",
    "invoice_paid": "invoice_paid",
    "outstanding_empty": "invoice_paid",
    "outstanding_cleared": "invoice_paid",
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
    if "cron" in text_lower:
        return ScheduleKind.cron
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


def _normalize_sources(raw_sources: Any, text: str, use_defaults: bool = True) -> list[str]:
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

    if not sources and use_defaults:
        return ["calendar", "tasks"]
    return sources


def _parse_output_mode(raw: str | None) -> OutputMode:
    if not raw:
        return OutputMode.compact
    value = raw.strip().lower().replace("-", "_")
    if value == "decision_ready":
        return OutputMode.decision_ready
    return OutputMode.compact


def _normalize_outcome_condition(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    return _OUTCOME_CONDITIONS.get(key)


def _derive_action_kind_and_completion(
    intent_data: dict[str, Any],
    text: str,
    sources: list[str],
) -> tuple[str, str | None]:
    kind_raw = str(intent_data.get("schedule_action_kind") or "").strip().lower()
    condition = _normalize_outcome_condition(intent_data.get("schedule_completion_condition"))
    text_lower = text.lower()

    explicit_outcome = kind_raw in {"outcome", "until_done", "persistent"}
    has_until_phrase = any(
        token in text_lower
        for token in ("until", "до ", "hasta ")
    )
    has_goal_signal = any(hint in text_lower for hint in _TASK_HINTS + _INVOICE_HINTS)
    hinted_outcome = any(hint in text_lower for hint in _OUTCOME_HINTS) or (
        has_until_phrase and has_goal_signal
    )
    is_outcome = explicit_outcome or hinted_outcome
    if not is_outcome:
        return "digest", None

    if condition:
        return "outcome", condition

    if "outstanding" in sources or any(hint in text_lower for hint in _INVOICE_HINTS):
        return "outcome", "invoice_paid"
    if "tasks" in sources or any(hint in text_lower for hint in _TASK_HINTS):
        return "outcome", "task_completed"
    return "outcome", "empty"


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


def _parse_max_runs(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value


def _extract_cron_expr(intent_data: dict[str, Any], message_text: str) -> str | None:
    candidates = [
        intent_data.get("cron_expr"),
        intent_data.get("schedule_time"),
        intent_data.get("schedule_instruction"),
    ]
    candidates.extend(re.findall(r"[\w*/,\-?#LW]+\s+[\w*/,\-?#LW]+\s+[\w*/,\-?#LW]+\s+"
                                 r"[\w*/,\-?#LW]+\s+[\w*/,\-?#LW]+", message_text))
    for raw in candidates:
        if not raw:
            continue
        value = str(raw).strip()
        if len(value.split()) not in {5, 6}:
            continue
        return value
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
    if schedule_kind == ScheduleKind.cron:
        return labels["cron"].format(expr="cron")
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

        timezone = context.timezone or "UTC"
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
        elif schedule_kind == ScheduleKind.cron:
            cron_expr = _extract_cron_expr(intent_data, message.text or "")
            if not cron_expr or not is_valid_cron_expression(cron_expr):
                return SkillResult(response_text=_t("ask_cron", language))
            schedule_config["cron_expr"] = cron_expr
            probe = SimpleNamespace(
                schedule_kind=ScheduleKind.cron,
                schedule_config=schedule_config,
                timezone=timezone,
                next_run_at=None,
            )
            next_run_at = compute_next_run(probe, after=now.astimezone(UTC))
            if next_run_at is None:
                return SkillResult(response_text=_t("ask_cron", language))
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
            next_run_at = _compute_recurring_next_run(
                schedule_kind=schedule_kind,
                now=now,
                hour=hour,
                minute=minute,
                weekday=weekday,
                day_of_month=day_of_month,
            )
            if schedule_kind == ScheduleKind.weekly:
                schedule_config["days"] = [weekday]
            if schedule_kind == ScheduleKind.monthly:
                schedule_config["day_of_month"] = day_of_month

        if next_run_at <= now:
            return SkillResult(response_text=_t("time_in_past", language))

        end_at = _parse_end_at(intent_data.get("schedule_end_date"))
        max_runs = _parse_max_runs(intent_data.get("schedule_max_runs"))
        validation_payload = {
            **schedule_config,
            "end_at": end_at,
            "max_runs": max_runs,
        }
        validation_payload.pop("run_at", None)
        try:
            ScheduleConfig(**validation_payload)
        except ValidationError as exc:
            fields = {
                str(item["loc"][0])
                for item in exc.errors()
                if item.get("loc")
            }
            if schedule_kind == ScheduleKind.cron or "cron_expr" in fields:
                return SkillResult(response_text=_t("ask_cron", language))
            if "time" in fields:
                return SkillResult(response_text=_t("ask_time", language))
            return SkillResult(response_text=_t("ask_schedule", language))

        output_mode = _parse_output_mode(intent_data.get("schedule_output_mode"))
        sources = _normalize_sources(intent_data.get("schedule_sources"), message.text or "")
        action_kind, completion_condition = _derive_action_kind_and_completion(
            intent_data,
            message.text or "",
            sources,
        )
        if action_kind == "outcome" and completion_condition:
            schedule_config["completion_condition"] = completion_condition
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
            action_kind=action_kind,
            schedule_kind=schedule_kind,
            schedule_config=schedule_config,
            sources=sources,
            output_mode=output_mode,
            timezone=timezone,
            language=language,
            status=ActionStatus.active,
            next_run_at=next_run_at,
            end_at=end_at,
            max_runs=max_runs,
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
        if schedule_kind == ScheduleKind.cron:
            schedule_desc = _SCHEDULE_LABELS.get(language, _SCHEDULE_LABELS["en"])["cron"].format(
                expr=schedule_config.get("cron_expr", "cron")
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
