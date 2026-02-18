"""Query report skill — generate and send PDF reports."""

import logging
from datetime import date
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.core.reports import generate_monthly_report
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = """Ты помогаешь с генерацией финансовых отчётов."""


def _parse_report_period(intent_data: dict[str, Any]) -> tuple[int, int]:
    """Extract year and month from intent_data.

    Supports: period="prev_month", date="2026-01-15", date_from="2026-01-01".
    Returns (year, month) for the report.
    """
    today = date.today()
    period = intent_data.get("period")

    if period == "prev_month":
        if today.month == 1:
            return today.year - 1, 12
        return today.year, today.month - 1

    # Try explicit date field (e.g. "report for January 2026")
    date_str = intent_data.get("date") or intent_data.get("date_from")
    if date_str:
        try:
            d = date.fromisoformat(date_str)
            return d.year, d.month
        except (ValueError, TypeError):
            pass

    # Default: current month
    return today.year, today.month


class QueryReportSkill:
    name = "query_report"
    intents = ["query_report"]
    model = "claude-sonnet-4-6"

    @observe(name="query_report")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Generate and return a PDF report."""
        try:
            year, month = _parse_report_period(intent_data)
            pdf_bytes, filename = await generate_monthly_report(
                family_id=context.family_id,
                year=year,
                month=month,
            )
            return SkillResult(
                response_text="Ваш ежемесячный отчёт готов:",
                document=pdf_bytes,
                document_name=filename,
            )
        except Exception as e:
            logger.error("Report generation failed: %s", e, exc_info=True)
            return SkillResult(
                response_text="Ошибка при генерации отчёта. Попробуйте позже.",
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return REPORT_SYSTEM_PROMPT


skill = QueryReportSkill()
