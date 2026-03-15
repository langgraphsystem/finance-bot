"""Custom event monitor skill.

Users say "notify me when Apple releases iPhone 17" or
"watch for concert tickets for Coldplay in Moscow" and the bot creates a
ScheduledAction with action_kind="event_watch" that checks hourly via
Gemini Google Search and fires a one-time notification when detected.
"""

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import get_session
from src.core.models.enums import ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.schedule_action.handler import (
    _compute_recurring_next_run,
)

logger = logging.getLogger(__name__)

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "ask_condition": (
            "What event should I watch for?\n"
            "Example: <i>Apple releases iPhone 17</i> or <i>concert tickets for Coldplay in Moscow</i>"
        ),
        "confirm": (
            "🔔 <b>Event monitor activated!</b>\n\n"
            "• Watching for: <b>{condition}</b>\n"
            "• Check interval: <b>every hour</b>\n"
            "• Max duration: <b>30 days</b>\n\n"
            "I'll search the web every hour and notify you the moment it happens."
        ),
    },
    "ru": {
        "ask_condition": (
            "За каким событием следить?\n"
            "Пример: <i>Apple выпустила iPhone 17</i> или <i>билеты на концерт Coldplay в Москве</i>"
        ),
        "confirm": (
            "🔔 <b>Мониторинг события запущен!</b>\n\n"
            "• Слежу за: <b>{condition}</b>\n"
            "• Проверка: <b>каждый час</b>\n"
            "• Максимум: <b>30 дней</b>\n\n"
            "Буду проверять каждый час и сразу сообщу, как только это произойдёт."
        ),
    },
    "es": {
        "ask_condition": (
            "¿Qué evento quieres monitorear?\n"
            "Ejemplo: <i>Apple lanza iPhone 17</i> o <i>entradas para Coldplay en Madrid</i>"
        ),
        "confirm": (
            "🔔 <b>¡Monitor de evento activado!</b>\n\n"
            "• Vigilando: <b>{condition}</b>\n"
            "• Intervalo: <b>cada hora</b>\n"
            "• Duración máxima: <b>30 días</b>\n\n"
            "Buscaré cada hora y te avisaré en cuanto ocurra."
        ),
    },
}

# Max checks: 24 per day × 30 days = 720
_MAX_RUNS = 720
# Cron: every hour on the hour
_CHECK_CRON = "0 * * * *"


def _t(key: str, lang: str, **kwargs: Any) -> str:
    strings = _STRINGS.get(lang, _STRINGS["en"])
    template = strings.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


class CustomEventSkill:
    name = "custom_event"
    intents = ["custom_event"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="custom_event")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        text = message.text or ""

        # 1. Resolve the event condition to watch for
        condition: str = (
            intent_data.get("event_condition")
            or intent_data.get("news_topic")
            or intent_data.get("search_query")
            or ""
        ).strip()
        if not condition:
            condition = text.strip()
        if not condition:
            return SkillResult(response_text=_t("ask_condition", lang))

        # 2. Schedule: hourly cron, next run in 1 hour
        timezone = getattr(context, "timezone", None) or "UTC"
        now = datetime.now(ZoneInfo(timezone))

        # First check: 1 hour from now (daily at current hour+1 as seed)
        next_run_at = _compute_recurring_next_run(
            schedule_kind=ScheduleKind.daily,
            now=now,
            hour=(now.hour + 1) % 24,
            minute=0,
            weekday=now.weekday(),
            day_of_month=now.day,
        )

        # 3. Persist ScheduledAction with event_watch kind
        action = ScheduledAction(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=f"🔔 {condition[:80]}",
            instruction=f"Monitor and detect when this event occurs: {condition}",
            action_kind="event_watch",
            sources=["event_check"],
            schedule_kind=ScheduleKind.cron,
            schedule_config={
                "event_condition": condition,
                "cron_expr": _CHECK_CRON,
                "completion_condition": "event_detected",
            },
            language=lang,
            timezone=timezone,
            next_run_at=next_run_at,
            max_runs=_MAX_RUNS,
        )

        async with get_session() as session:
            session.add(action)
            await session.commit()

        logger.info(
            "CustomEvent created: action_id=%s condition=%r next_run=%s user_id=%s",
            action.id,
            condition,
            next_run_at,
            context.user_id,
        )

        return SkillResult(response_text=_t("confirm", lang, condition=condition))


skill = CustomEventSkill()
