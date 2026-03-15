"""News monitor skill — create a scheduled news/topic digest.

Users say "monitor AI news every day at 9am" and the bot creates a
ScheduledAction with sources=["news"] that runs dual_search at the given
time and delivers a fresh digest to Telegram.
"""

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult
from src.skills.schedule_action.handler import (
    _compute_recurring_next_run,
    _parse_schedule_kind,
    _parse_time_parts,
    _parse_weekday,
)

logger = logging.getLogger(__name__)

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "ask_topic": (
            "What topic would you like me to monitor?\n"
            "Example: <i>AI news daily at 9am</i> or <i>crypto every evening at 20:00</i>"
        ),
        "confirm": (
            "📰 <b>Digest scheduled!</b>\n\n"
            "• Topic: <b>{topic}</b>\n"
            "• Sources: {sources}\n"
            "• Schedule: <b>{schedule}</b>\n"
            "• First delivery: <b>{next_run}</b>\n\n"
            "I'll collect everything and send you a fresh digest at that time."
        ),
        "confirm_no_topic": (
            "🗓 <b>Digest scheduled!</b>\n\n"
            "• Sources: {sources}\n"
            "• Schedule: <b>{schedule}</b>\n"
            "• First delivery: <b>{next_run}</b>\n\n"
            "I'll gather the latest and send it at that time."
        ),
        "schedule_daily": "daily at {time}",
        "schedule_weekly": "weekly on {day} at {time}",
        "schedule_once": "once at {time}",
    },
    "ru": {
        "ask_topic": (
            "На какую тему следить за новостями?\n"
            "Пример: <i>новости про ИИ каждый день в 9:00</i> или <i>крипто каждый вечер в 20:00</i>"
        ),
        "confirm": (
            "📰 <b>Дайджест запланирован!</b>\n\n"
            "• Тема: <b>{topic}</b>\n"
            "• Источники: {sources}\n"
            "• Расписание: <b>{schedule}</b>\n"
            "• Первая доставка: <b>{next_run}</b>\n\n"
            "В указанное время соберу всё актуальное и пришлю дайджест."
        ),
        "confirm_no_topic": (
            "🗓 <b>Дайджест запланирован!</b>\n\n"
            "• Источники: {sources}\n"
            "• Расписание: <b>{schedule}</b>\n"
            "• Первая доставка: <b>{next_run}</b>\n\n"
            "В указанное время соберу и пришлю."
        ),
        "schedule_daily": "каждый день в {time}",
        "schedule_weekly": "каждую неделю ({day}) в {time}",
        "schedule_once": "один раз в {time}",
    },
    "es": {
        "ask_topic": (
            "¿Qué tema quieres monitorear?\n"
            "Ejemplo: <i>noticias de IA todos los días a las 9am</i>"
        ),
        "confirm": (
            "📰 <b>¡Resumen programado!</b>\n\n"
            "• Tema: <b>{topic}</b>\n"
            "• Fuentes: {sources}\n"
            "• Horario: <b>{schedule}</b>\n"
            "• Primera entrega: <b>{next_run}</b>\n\n"
            "Recopilaré todo y te lo enviaré a esa hora."
        ),
        "confirm_no_topic": (
            "🗓 <b>¡Resumen programado!</b>\n\n"
            "• Fuentes: {sources}\n"
            "• Horario: <b>{schedule}</b>\n"
            "• Primera entrega: <b>{next_run}</b>\n\n"
            "Lo recopilaré y te lo enviaré a esa hora."
        ),
        "schedule_daily": "diariamente a las {time}",
        "schedule_weekly": "semanalmente el {day} a las {time}",
        "schedule_once": "una vez a las {time}",
    },
}

_WEEKDAY_NAMES = {
    0: {"en": "Monday",    "ru": "пн", "es": "lunes"},
    1: {"en": "Tuesday",   "ru": "вт", "es": "martes"},
    2: {"en": "Wednesday", "ru": "ср", "es": "miércoles"},
    3: {"en": "Thursday",  "ru": "чт", "es": "jueves"},
    4: {"en": "Friday",    "ru": "пт", "es": "viernes"},
    5: {"en": "Saturday",  "ru": "сб", "es": "sábado"},
    6: {"en": "Sunday",    "ru": "вс", "es": "domingo"},
}

# Human-readable labels for each supported source
_SOURCE_LABELS: dict[str, dict[str, str]] = {
    "news":             {"en": "📰 News",     "ru": "📰 Новости",   "es": "📰 Noticias"},
    "calendar":         {"en": "📅 Calendar", "ru": "📅 Календарь", "es": "📅 Calendario"},
    "tasks":            {"en": "✅ Tasks",    "ru": "✅ Задачи",    "es": "✅ Tareas"},
    "money_summary":    {"en": "💰 Finance",  "ru": "💰 Финансы",   "es": "💰 Finanzas"},
    "email_highlights": {"en": "📧 Email",    "ru": "📧 Email",     "es": "📧 Email"},
    "outstanding":      {"en": "🔔 Payments", "ru": "🔔 Платежи",   "es": "🔔 Pagos"},
}

_VALID_SOURCES = set(_SOURCE_LABELS.keys())


def _resolve_sources(intent_data: dict, topic: str) -> list[str]:
    """Merge intent-extracted sources with news (always included when topic present).

    Rules:
    - If user specified schedule_sources, honour them exactly.
    - Always include "news" when a topic is given.
    - Strip unknown source names so collectors never crash.
    - Preserve insertion order, dedup.
    """
    extra: list[str] = intent_data.get("schedule_sources") or []
    sources: list[str] = []
    seen: set[str] = set()

    # news first if topic provided
    if topic:
        sources.append("news")
        seen.add("news")

    for src in extra:
        if src in _VALID_SOURCES and src not in seen:
            sources.append(src)
            seen.add(src)

    # fallback: at minimum news
    return sources or ["news"]


def _sources_label(sources: list[str], lang: str) -> str:
    """Return a comma-joined human-readable list of sources."""
    labels = [_SOURCE_LABELS.get(s, {}).get(lang, _SOURCE_LABELS.get(s, {}).get("en", s))
              for s in sources]
    return ", ".join(labels)


def _t(key: str, lang: str, **kwargs: Any) -> str:
    strings = _STRINGS.get(lang, _STRINGS["en"])
    template = strings.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def _weekday_name(weekday: int, lang: str) -> str:
    return _WEEKDAY_NAMES.get(weekday, {}).get(lang, _WEEKDAY_NAMES[0]["en"])


def _schedule_label(kind: ScheduleKind, time_str: str, lang: str, weekday: int) -> str:
    if kind == ScheduleKind.weekly:
        return _t("schedule_weekly", lang, day=_weekday_name(weekday, lang), time=time_str)
    if kind == ScheduleKind.once:
        return _t("schedule_once", lang, time=time_str)
    return _t("schedule_daily", lang, time=time_str)


register_strings("news_monitor", {"en": {}, "ru": {}, "es": {}})


class NewsMonitorSkill:
    name = "news_monitor"
    intents = ["news_monitor"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="news_monitor")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        text = message.text or ""

        # 1. Resolve topic from LLM-extracted fields
        topic: str = (
            intent_data.get("news_topic")
            or intent_data.get("search_topic")
            or intent_data.get("search_query")
            or ""
        ).strip()
        if not topic:
            topic = text.strip()

        # Require topic OR at least one extra source; otherwise ask
        extra_sources: list[str] = intent_data.get("schedule_sources") or []
        if not topic and not extra_sources:
            return SkillResult(response_text=_t("ask_topic", lang))

        # 2. Merge sources: news (when topic) + any extras from intent
        sources = _resolve_sources(intent_data, topic)

        # 3. Resolve schedule kind (daily by default for news)
        schedule_kind: ScheduleKind = _parse_schedule_kind(intent_data, text) or ScheduleKind.daily

        # 4. Resolve delivery time (09:00 default)
        time_parts = _parse_time_parts(intent_data.get("schedule_time"))
        hour, minute = time_parts if time_parts else (9, 0)
        time_str = f"{hour:02d}:{minute:02d}"

        # 5. Current local time for schedule computation
        timezone = getattr(context, "timezone", None) or "UTC"
        now = datetime.now(ZoneInfo(timezone))

        weekday = _parse_weekday(intent_data, text, now)
        day_of_month = now.day

        # 6. Compute next run
        next_run_at = _compute_recurring_next_run(
            schedule_kind=schedule_kind,
            now=now,
            hour=hour,
            minute=minute,
            weekday=weekday,
            day_of_month=day_of_month,
        )

        # Build title and instruction
        if topic:
            title = f"📰 {topic[:80]}"
            instruction = f"Search and summarize: {topic}"
            if len(sources) > 1:
                extras = [s for s in sources if s != "news"]
                instruction += f". Also include: {', '.join(extras)}."
        else:
            title = "🗓 " + _sources_label(sources, lang)[:80]
            instruction = f"Collect and summarize: {', '.join(sources)}."

        # 7. Persist ScheduledAction
        action = ScheduledAction(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=title,
            instruction=instruction,
            sources=sources,
            schedule_kind=schedule_kind,
            schedule_config={
                "news_topic": topic,
                "time": time_str,
                "day_of_week": intent_data.get("schedule_day_of_week") or "",
            },
            language=lang,
            timezone=timezone,
            next_run_at=next_run_at,
        )

        async with async_session() as session:
            session.add(action)
            await session.commit()

        logger.info(
            "NewsMonitor created: action_id=%s topic=%r sources=%s schedule_kind=%s next_run=%s user_id=%s",
            action.id,
            topic,
            sources,
            schedule_kind.value,
            next_run_at,
            context.user_id,
        )

        # 8. Confirm to user
        schedule_label = _schedule_label(schedule_kind, time_str, lang, weekday)
        next_run_str = next_run_at.strftime("%d %b %Y %H:%M") if next_run_at else time_str
        sources_label = _sources_label(sources, lang)

        confirm_key = "confirm" if topic else "confirm_no_topic"
        confirm_kwargs: dict = {"sources": sources_label, "schedule": schedule_label, "next_run": next_run_str}
        if topic:
            confirm_kwargs["topic"] = topic

        return SkillResult(response_text=_t(confirm_key, lang, **confirm_kwargs))


skill = NewsMonitorSkill()
