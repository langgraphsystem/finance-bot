"""List scheduled actions skill."""

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.core.scheduled_actions.i18n import (
    SCHEDULE_LABELS,
    WEEKDAY_NAMES,
)
from src.gateway.types import IncomingMessage
from src.skills._i18n import fmt_date, fmt_time, register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

LIST_SCHEDULED_ACTIONS_PROMPT = """\
You help users view their scheduled actions.
List each action with status, schedule, and next run time.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""

_STRINGS = {
    "en": {
        "disabled": "Scheduled actions are not enabled yet.",
        "header": "📋 <b>Your scheduled actions</b>",
        "empty": (
            "No scheduled actions yet.\n"
            '<i>Try: "Every day at 8 send me calendar and tasks"</i>'
        ),
        "next": "Next run",
    },
    "ru": {
        "disabled": "Запланированные действия пока не включены.",
        "header": "📋 <b>Ваши запланированные действия</b>",
        "empty": (
            "Пока нет запланированных действий.\n"
            '<i>Попробуйте: "Каждый день в 8 отправляй календарь и задачи"</i>'
        ),
        "next": "Следующий запуск",
    },
    "es": {
        "disabled": "Las acciones programadas aún no están habilitadas.",
        "header": "📋 <b>Tus acciones programadas</b>",
        "empty": (
            "Aún no tienes acciones programadas.\n"
            '<i>Prueba: "Cada día a las 8 envíame calendario y tareas"</i>'
        ),
        "next": "Próxima ejecución",
    },
}
register_strings("list_scheduled_actions", _STRINGS)

_STATUS_ICON = {
    ActionStatus.active: "▶️",
    ActionStatus.paused: "⏸",
    ActionStatus.completed: "✅",
    ActionStatus.deleted: "🗑",
}

_SCHEDULE_LABELS = SCHEDULE_LABELS
_WEEKDAYS = WEEKDAY_NAMES


def _t(key: str, language: str) -> str:
    strings = _STRINGS.get(language, _STRINGS["en"])
    return strings[key]


def _schedule_description(action: ScheduledAction, language: str) -> str:
    labels = _SCHEDULE_LABELS.get(language, _SCHEDULE_LABELS["en"])
    timezone = action.timezone
    tz = ZoneInfo(timezone)
    cfg = action.schedule_config or {}
    kind = action.schedule_kind

    if kind == ScheduleKind.once and action.next_run_at:
        return labels["once"].format(dt=fmt_date(action.next_run_at, language, timezone=timezone))

    if kind in {ScheduleKind.daily, ScheduleKind.weekdays}:
        raw_time = cfg.get("time")
        if raw_time:
            hh, mm = str(raw_time).split(":", maxsplit=1)
            fake_dt = datetime.now(tz).replace(
                hour=int(hh), minute=int(mm), second=0, microsecond=0,
            )
            label = "daily" if kind == ScheduleKind.daily else "weekdays"
            return labels[label].format(
                time=fmt_time(fake_dt, language, timezone=timezone),
            )

    if kind == ScheduleKind.weekly:
        days = cfg.get("days") or [0]
        day_idx = int(days[0]) if days else 0
        day = _WEEKDAYS.get(language, _WEEKDAYS["en"])[day_idx]
        raw_time = str(cfg.get("time", "09:00"))
        hh, mm = raw_time.split(":", maxsplit=1)
        fake_dt = datetime.now(tz).replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        return labels["weekly"].format(day=day, time=fmt_time(fake_dt, language, timezone=timezone))

    if kind == ScheduleKind.monthly:
        dom = int(cfg.get("day_of_month") or 1)
        raw_time = str(cfg.get("time", "09:00"))
        hh, mm = raw_time.split(":", maxsplit=1)
        fake_dt = datetime.now(tz).replace(
            hour=int(hh), minute=int(mm), second=0, microsecond=0,
        )
        return labels["monthly"].format(
            day=dom, time=fmt_time(fake_dt, language, timezone=timezone),
        )

    if kind == ScheduleKind.cron:
        return labels["cron"]

    if action.next_run_at:
        return labels["once"].format(dt=fmt_date(action.next_run_at, language, timezone=timezone))
    return labels["daily"].format(time="09:00")


class ListScheduledActionsSkill:
    name = "list_scheduled_actions"
    intents = ["list_scheduled_actions"]
    model = "gpt-5.2"

    @observe(name="list_scheduled_actions")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        del message, intent_data

        lang = context.language or "en"
        if not settings.ff_scheduled_actions:
            return SkillResult(response_text=_t("disabled", lang))

        actions = await get_scheduled_actions(context.family_id, context.user_id)
        if not actions:
            return SkillResult(response_text=_t("empty", lang))

        lines = [_t("header", lang), ""]
        for idx, action in enumerate(actions, start=1):
            icon = _STATUS_ICON.get(action.status, "•")
            desc = _schedule_description(action, lang)
            next_run = "—"
            if action.next_run_at:
                next_run = fmt_date(action.next_run_at, lang, timezone=action.timezone)
            lines.append(
                f"{idx}. {icon} <b>{action.title}</b>\n"
                f"   {desc} · {_t('next', lang)}: {next_run}"
            )
            lines.append("")

        return SkillResult(response_text="\n".join(lines).strip())

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_SCHEDULED_ACTIONS_PROMPT.format(language=context.language or "en")


async def get_scheduled_actions(family_id: str, user_id: str) -> list[ScheduledAction]:
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledAction)
            .where(
                ScheduledAction.family_id == uuid.UUID(family_id),
                ScheduledAction.user_id == uuid.UUID(user_id),
                ScheduledAction.status.in_(
                    [ActionStatus.active, ActionStatus.paused, ActionStatus.completed]
                ),
            )
            .order_by(
                ScheduledAction.next_run_at.asc().nulls_last(),
                ScheduledAction.created_at.asc(),
            )
            .limit(50)
        )
        return list(result.scalars().all())


skill = ListScheduledActionsSkill()
