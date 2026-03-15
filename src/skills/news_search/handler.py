"""News Search skill — immediate one-time internet news collection on a topic.

Users say "найди новости про Tesla" or "what's happening with AI" and the bot
immediately searches the internet via Gemini Google Search and returns a digest.
Subscribe buttons allow converting to a scheduled digest (via news_monitor).
"""

import json
import logging
import secrets
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import get_session
from src.core.db import redis as redis_client
from src.core.models.enums import ScheduleKind
from src.core.models.scheduled_action import ScheduledAction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.schedule_action.handler import (
    _compute_recurring_next_run,
)

logger = logging.getLogger(__name__)

# Redis TTL for subscribe pending data (24h)
_NEWS_SUB_TTL = 86400

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "ask_topic": (
            "What topic would you like me to search news for?\n"
            "Example: <i>Tesla</i> or <i>crypto market</i>"
        ),
        "searching": "🔍 Searching for the latest news on <b>{topic}</b>…",
        "no_results": "Couldn't find recent news on <b>{topic}</b>. Try rephrasing the query.",
        "header": "📰 <b>Latest news: {topic}</b>\n\n",
        "subscribe_prompt": "\n\n<i>Want regular updates on this topic?</i>",
        "btn_daily": "📅 Daily at 9:00",
        "btn_weekly": "📆 Once a week",
        "btn_custom": "⚙️ Custom schedule",
        "subscribed": (
            "✅ <b>Subscribed!</b> I'll send you <b>{topic}</b> news {schedule}.\n"
            "First delivery: <b>{next_run}</b>"
        ),
        "subscribed_daily": "every day at 9:00",
        "subscribed_weekly": "every Monday at 9:00",
    },
    "ru": {
        "ask_topic": (
            "По какой теме искать новости?\n"
            "Пример: <i>Tesla</i> или <i>крипторынок</i>"
        ),
        "searching": "🔍 Ищу свежие новости по теме <b>{topic}</b>…",
        "no_results": "Не удалось найти свежие новости по теме <b>{topic}</b>. Попробуй переформулировать.",
        "header": "📰 <b>Последние новости: {topic}</b>\n\n",
        "subscribe_prompt": "\n\n<i>Хочешь получать обновления по этой теме регулярно?</i>",
        "btn_daily": "📅 Ежедневно в 9:00",
        "btn_weekly": "📆 Раз в неделю",
        "btn_custom": "⚙️ Своё расписание",
        "subscribed": (
            "✅ <b>Подписка оформлена!</b> Буду присылать новости по теме <b>{topic}</b> {schedule}.\n"
            "Первая доставка: <b>{next_run}</b>"
        ),
        "subscribed_daily": "каждый день в 9:00",
        "subscribed_weekly": "каждый понедельник в 9:00",
    },
    "es": {
        "ask_topic": (
            "¿Sobre qué tema quieres buscar noticias?\n"
            "Ejemplo: <i>Tesla</i> o <i>mercado cripto</i>"
        ),
        "searching": "🔍 Buscando las últimas noticias sobre <b>{topic}</b>…",
        "no_results": "No encontré noticias recientes sobre <b>{topic}</b>. Intenta reformular.",
        "header": "📰 <b>Últimas noticias: {topic}</b>\n\n",
        "subscribe_prompt": "\n\n<i>¿Quieres recibir actualizaciones sobre este tema regularmente?</i>",
        "btn_daily": "📅 Diariamente a las 9:00",
        "btn_weekly": "📆 Una vez a la semana",
        "btn_custom": "⚙️ Horario personalizado",
        "subscribed": (
            "✅ <b>¡Suscrito!</b> Te enviaré noticias sobre <b>{topic}</b> {schedule}.\n"
            "Primera entrega: <b>{next_run}</b>"
        ),
        "subscribed_daily": "todos los días a las 9:00",
        "subscribed_weekly": "cada lunes a las 9:00",
    },
}

_LANG_NAMES: dict[str, str] = {
    "en": "English", "ru": "Russian", "es": "Spanish",
    "de": "German", "fr": "French", "it": "Italian",
    "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese",
    "ar": "Arabic", "tr": "Turkish", "pl": "Polish",
}


def _t(key: str, lang: str, **kwargs: Any) -> str:
    strings = _STRINGS.get(lang, _STRINGS["en"])
    template = strings.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


async def _search_news(topic: str, language: str) -> str:
    """Search for latest news via Gemini Google Search grounding."""
    from google.genai import types  # lazy import

    from src.core.llm.clients import google_client  # lazy import

    lang_name = _LANG_NAMES.get(language, "English")
    prompt = (
        f"Find the latest news and updates about: {topic}\n\n"
        f"Requirements:\n"
        f"- Respond ONLY in {lang_name}\n"
        f"- Use Telegram HTML formatting (<b>, <i>) — no Markdown\n"
        f"- List results as bullet points (• item)\n"
        f"- Include source name in <i>italics</i> after each item\n"
        f"- Max 8 items, prioritise recency (last 48 hours)\n"
        f"- Add publication date/time where available\n"
        f"- Skip paywalled or unavailable articles\n"
        f"- If no news found in last 48h, include last 7 days with a note"
    )

    client = google_client()
    response = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return response.text or ""


async def create_news_subscription(
    topic: str,
    kind: str,  # "daily" or "weekly"
    user_id: str,
    family_id: str,
    language: str,
    timezone: str,
) -> tuple[str, str]:
    """Create a ScheduledAction for recurring news. Returns (schedule_label, next_run_str)."""
    schedule_kind = ScheduleKind.weekly if kind == "weekly" else ScheduleKind.daily
    hour, minute = 9, 0
    now = datetime.now(ZoneInfo(timezone))

    # For weekly: use Monday (0)
    weekday = 0 if kind == "weekly" else now.weekday()

    next_run_at = _compute_recurring_next_run(
        schedule_kind=schedule_kind,
        now=now,
        hour=hour,
        minute=minute,
        weekday=weekday,
        day_of_month=now.day,
    )

    action = ScheduledAction(
        id=uuid.uuid4(),
        family_id=uuid.UUID(family_id),
        user_id=uuid.UUID(user_id),
        title=f"📰 {topic[:80]}",
        instruction=f"Search and summarize: {topic}",
        sources=["news"],
        schedule_kind=schedule_kind,
        schedule_config={
            "news_topic": topic,
            "time": f"{hour:02d}:{minute:02d}",
            "day_of_week": "monday" if kind == "weekly" else "",
        },
        language=language,
        timezone=timezone,
        next_run_at=next_run_at,
    )

    async with get_session() as session:
        session.add(action)
        await session.commit()

    lang = language or "en"
    schedule_label = _t(f"subscribed_{kind}", lang)
    next_run_str = next_run_at.strftime("%d %b %Y %H:%M") if next_run_at else "09:00"

    logger.info(
        "NewsSearch subscription created: action_id=%s topic=%r kind=%s user_id=%s",
        action.id, topic, kind, user_id,
    )
    return schedule_label, next_run_str


class NewsSearchSkill:
    name = "news_search"
    intents = ["news_search"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="news_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"

        # 1. Resolve topic
        topic: str = (
            intent_data.get("news_topic")
            or intent_data.get("search_topic")
            or intent_data.get("search_query")
            or ""
        ).strip()
        if not topic:
            topic = (message.text or "").strip()
        if not topic:
            return SkillResult(response_text=_t("ask_topic", lang))

        # 2. Search news
        try:
            results = await _search_news(topic, lang)
        except Exception as exc:
            logger.warning("NewsSearch failed for topic=%r: %s", topic, exc)
            results = ""

        if not results:
            return SkillResult(response_text=_t("no_results", lang, topic=topic))

        # 3. Format response
        text = _t("header", lang, topic=topic) + results + _t("subscribe_prompt", lang)

        # 4. Store topic in Redis for subscribe callbacks
        pending_id = secrets.token_hex(4)  # 8 chars
        pending_data = {
            "topic": topic,
            "user_id": context.user_id,
            "family_id": context.family_id,
            "language": lang,
            "timezone": getattr(context, "timezone", None) or "UTC",
        }
        await redis_client.set(
            f"news_sub:{pending_id}",
            json.dumps(pending_data),
            ex=_NEWS_SUB_TTL,
        )

        # 5. Subscribe buttons
        buttons = [
            {"text": _t("btn_daily", lang), "callback": f"news_sub:{pending_id}:daily"},
            {"text": _t("btn_weekly", lang), "callback": f"news_sub:{pending_id}:weekly"},
            {"text": _t("btn_custom", lang), "callback": f"news_sub:{pending_id}:custom"},
        ]

        return SkillResult(response_text=text, buttons=buttons)


skill = NewsSearchSkill()
