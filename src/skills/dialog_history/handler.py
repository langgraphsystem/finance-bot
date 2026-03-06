"""Skill: dialog_history — search past conversations.

Handles: "о чём мы говорили вчера?", "what did we discuss last week?",
"какие идеи были на этой неделе?", "our conversation history".
"""

import logging
from datetime import date, timedelta

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
        from src.core.models.session_summary import SessionSummary

        text = message.text or ""
        language = context.language or "en"

        # Determine search period
        period = _detect_period(text)
        start_date = _period_to_date(period)

        try:
            async with async_session() as session:
                query = (
                    select(SessionSummary)
                    .where(
                        SessionSummary.user_id == context.user_id,
                        SessionSummary.created_at >= start_date,
                    )
                    .order_by(SessionSummary.created_at.desc())
                    .limit(10)
                )
                result = await session.execute(query)
                summaries = result.scalars().all()

            if not summaries:
                return SkillResult(
                    response_text=_no_history_msg(period, language),
                )

            # Format summaries
            lines: list[str] = []
            for s in summaries:
                dt = s.created_at.strftime("%d.%m %H:%M") if s.created_at else "?"
                summary_text = (s.summary or "")[:200]
                lines.append(f"<b>{dt}</b>: {summary_text}")

            header = _header_msg(period, language)
            body = "\n\n".join(lines)
            return SkillResult(response_text=f"{header}\n\n{body}")

        except Exception as e:
            logger.error("Dialog history search failed: %s", e)
            return SkillResult(
                response_text="Failed to search dialog history." if language != "ru"
                else "Не удалось найти историю диалогов.",
            )


def _detect_period(text: str) -> str:
    """Detect time period from text."""
    lower = text.lower()

    yesterday_markers = ["вчера", "yesterday", "ayer", "gestern", "hier"]
    week_markers = ["неделе", "недел", "week", "semana", "woche"]
    month_markers = ["месяц", "month", "mes", "monat"]
    today_markers = ["сегодня", "today", "hoy", "heute"]

    for m in yesterday_markers:
        if m in lower:
            return "yesterday"
    for m in week_markers:
        if m in lower:
            return "week"
    for m in month_markers:
        if m in lower:
            return "month"
    for m in today_markers:
        if m in lower:
            return "today"
    return "week"  # Default to week


def _period_to_date(period: str) -> date:
    """Convert period string to start date."""
    today = date.today()
    if period == "today":
        return today
    if period == "yesterday":
        return today - timedelta(days=1)
    if period == "week":
        return today - timedelta(weeks=1)
    if period == "month":
        return today - timedelta(days=30)
    return today - timedelta(weeks=1)


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
