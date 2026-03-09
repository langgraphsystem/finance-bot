"""Skill: dialog_history - search past conversations.

Handles: "о чём мы говорили вчера?", "what did we discuss last week?",
"какие идеи были на этой неделе?", "our conversation history".
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class DialogHistorySkill(BaseSkill):
    name = "dialog_history"
    intents = ["dialog_history"]
    model = "gemini-3.1-flash-lite-preview"

    def get_system_prompt(self, context) -> str:  # noqa: ANN001, ARG002
        return ""

    async def execute(self, message, context, intent_data=None) -> SkillResult:  # noqa: ANN001
        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.conversation import ConversationMessage
        from src.core.models.session_summary import SessionSummary

        text = message.text or ""
        language = context.language or "en"

        period = _detect_period(text)
        start_at, end_at = _period_bounds(period, getattr(context, "timezone", None))
        user_id = uuid.UUID(str(context.user_id))

        try:
            async with async_session() as session:
                query = (
                    select(SessionSummary)
                    .where(
                        SessionSummary.user_id == user_id,
                        SessionSummary.updated_at >= start_at,
                    )
                    .order_by(SessionSummary.updated_at.desc())
                    .limit(10)
                )
                if end_at is not None:
                    query = query.where(SessionSummary.updated_at < end_at)
                summary_result = await session.execute(query)
                summaries = summary_result.scalars().all()

                if summaries:
                    return SkillResult(
                        response_text=_format_summaries(period, language, summaries)
                    )

                message_query = (
                    select(ConversationMessage)
                    .where(
                        ConversationMessage.user_id == user_id,
                        ConversationMessage.created_at >= start_at,
                    )
                    .order_by(ConversationMessage.created_at.asc())
                    .limit(24)
                )
                if end_at is not None:
                    message_query = message_query.where(ConversationMessage.created_at < end_at)
                msg_result = await session.execute(message_query)
                messages = msg_result.scalars().all()

            if not messages:
                return SkillResult(response_text=_no_history_msg(period, language))

            return SkillResult(response_text=_format_messages(period, language, messages))

        except Exception as exc:
            logger.error("Dialog history search failed: %s", exc)
            return SkillResult(
                response_text=(
                    "Failed to search dialog history."
                    if language != "ru"
                    else "Не удалось найти историю диалогов."
                ),
            )


def _format_summaries(period: str, language: str, summaries) -> str:  # noqa: ANN001
    header = _header_msg(period, language)
    lines: list[str] = []
    for summary in summaries:
        dt_value = summary.updated_at or summary.created_at
        dt = dt_value.strftime("%d.%m %H:%M") if dt_value else "?"
        summary_text = (summary.summary or "")[:200]
        lines.append(f"<b>{dt}</b>: {summary_text}")
    body = "\n\n".join(lines)
    return f"{header}\n\n{body}"


def _format_messages(period: str, language: str, messages) -> str:  # noqa: ANN001
    header = _header_msg(period, language)
    is_ru = language and language.startswith("ru")
    user_label = "Вы" if is_ru else "You"
    assistant_label = "Бот" if is_ru else "Bot"

    lines: list[str] = []
    for item in messages[-12:]:
        dt = item.created_at.strftime("%d.%m %H:%M") if item.created_at else "?"
        role_value = getattr(item.role, "value", str(item.role))
        label = user_label if role_value == "user" else assistant_label
        content = (item.content or "").strip().replace("\n", " ")
        if len(content) > 140:
            content = f"{content[:137]}..."
        lines.append(f"<b>{dt}</b> {label}: {content}")

    return f"{header}\n\n" + "\n".join(lines)



def _detect_period(text: str) -> str:
    """Detect time period from text."""
    lower = text.lower()

    yesterday_markers = ["вчера", "yesterday", "ayer", "gestern", "hier"]
    week_markers = ["неделе", "недел", "week", "semana", "woche"]
    month_markers = ["месяц", "month", "mes", "monat"]
    today_markers = ["сегодня", "today", "hoy", "heute"]

    for marker in yesterday_markers:
        if marker in lower:
            return "yesterday"
    for marker in week_markers:
        if marker in lower:
            return "week"
    for marker in month_markers:
        if marker in lower:
            return "month"
    for marker in today_markers:
        if marker in lower:
            return "today"
    return "week"



def _resolve_timezone(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone for dialog_history: %s", tz_name)
        return ZoneInfo("UTC")



def _period_bounds(period: str, tz_name: str | None) -> tuple[datetime, datetime | None]:
    """Return inclusive start and exclusive end datetimes for the requested period."""
    tz = _resolve_timezone(tz_name)
    now_local = datetime.now(tz)
    start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        return start_of_today.astimezone(UTC), None
    if period == "yesterday":
        start = start_of_today - timedelta(days=1)
        end = start_of_today
        return start.astimezone(UTC), end.astimezone(UTC)
    if period == "week":
        start = start_of_today - timedelta(weeks=1)
        return start.astimezone(UTC), None
    if period == "month":
        start = start_of_today - timedelta(days=30)
        return start.astimezone(UTC), None
    start = start_of_today - timedelta(weeks=1)
    return start.astimezone(UTC), None



def _header_msg(period: str, language: str) -> str:
    is_ru = language and language.startswith("ru")
    headers = {
        "today": ("Сегодняшние разговоры:", "Today's conversations:"),
        "yesterday": ("Вчерашние разговоры:", "Yesterday's conversations:"),
        "week": ("Разговоры за неделю:", "This week's conversations:"),
        "month": ("Разговоры за месяц:", "This month's conversations:"),
    }
    ru, en = headers.get(period, headers["week"])
    return ru if is_ru else en



def _no_history_msg(period: str, language: str) -> str:
    is_ru = language and language.startswith("ru")
    if is_ru:
        return f"Нет сохранённых разговоров за этот период ({period})."
    return f"No saved conversations for this period ({period})."


skill = DialogHistorySkill()
