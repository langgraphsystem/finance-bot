"""Query report skill — generate and send PDF reports."""

import logging
from datetime import date
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.core.reports import (
    MONTH_NAMES_I18N,
    generate_monthly_report,
    has_transactions_for_period,
)
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "report_ready": "Your monthly report is ready:",
        "report_error": "Error generating the report. Please try again later.",
        "no_data": (
            "No transactions found for {period}. "
            "Try specifying a different period, e.g. \"report for February\"."
        ),
        "no_data_fallback": (
            "No transactions found for {period}. "
            "Here's the report for {fallback_period} instead:"
        ),
    },
    "ru": {
        "report_ready": "Ваш ежемесячный отчёт готов:",
        "report_error": "Ошибка при генерации отчёта. Попробуйте позже.",
        "no_data": (
            "За {period} транзакций не найдено. "
            "Попробуйте указать другой период, например «отчёт за февраль»."
        ),
        "no_data_fallback": (
            "За {period} транзакций не найдено. "
            "Вот отчёт за {fallback_period}:"
        ),
    },
    "es": {
        "report_ready": "Su informe mensual está listo:",
        "report_error": "Error al generar el informe. Inténtelo más tarde.",
        "no_data": (
            "No se encontraron transacciones para {period}. "
            "Intente especificar otro período, p. ej. \"informe de febrero\"."
        ),
        "no_data_fallback": (
            "No se encontraron transacciones para {period}. "
            "Aquí está el informe de {fallback_period}:"
        ),
    },
}
register_strings("query_report", _STRINGS)

_DEFAULT_SYSTEM_PROMPT = """\
You help the user generate financial reports.
Respond in: {language}."""


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the previous month."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _month_label(year: int, month: int, lang: str) -> str:
    """Human-readable month label like 'Март 2026'."""
    names = MONTH_NAMES_I18N.get(lang, MONTH_NAMES_I18N["en"])
    return f"{names[month]} {year}"


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


def _user_explicitly_chose_period(intent_data: dict[str, Any]) -> bool:
    """Check if the user specified a concrete period (vs. defaulting to current month)."""
    return bool(
        intent_data.get("period")
        or intent_data.get("date")
        or intent_data.get("date_from")
    )


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
        lang = context.language or "en"

        # Ask for period if request is ambiguous
        from src.skills._clarification import maybe_ask_period

        clarify = await maybe_ask_period(
            "query_report", intent_data, message.text or "",
            context.user_id, lang,
        )
        if clarify:
            return clarify

        try:
            year, month = _parse_report_period(intent_data)
            explicit = _user_explicitly_chose_period(intent_data)

            # Check if there's any data for the requested period
            has_data = await has_transactions_for_period(
                context.family_id, year, month
            )

            if not has_data:
                # If user didn't specify a period, try previous month
                if not explicit:
                    py, pm = _prev_month(year, month)
                    has_prev = await has_transactions_for_period(
                        context.family_id, py, pm
                    )
                    if has_prev:
                        # Generate report for previous month instead
                        pdf_bytes, filename = await generate_monthly_report(
                            family_id=context.family_id,
                            year=py,
                            month=pm,
                            language=lang,
                        )
                        msg = t_cached(
                            _STRINGS, "no_data_fallback", lang,
                            namespace="query_report",
                        ).format(
                            period=_month_label(year, month, lang),
                            fallback_period=_month_label(py, pm, lang),
                        )
                        return SkillResult(
                            response_text=msg,
                            document=pdf_bytes,
                            document_name=filename,
                        )

                # No data at all — return helpful text
                msg = t_cached(
                    _STRINGS, "no_data", lang, namespace="query_report",
                ).format(period=_month_label(year, month, lang))
                return SkillResult(response_text=msg)

            # Normal path: generate and return PDF
            pdf_bytes, filename = await generate_monthly_report(
                family_id=context.family_id,
                year=year,
                month=month,
                language=lang,
            )
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "report_ready", lang, namespace="query_report"
                ),
                document=pdf_bytes,
                document_name=filename,
            )
        except Exception as e:
            logger.error("Report generation failed: %s", e, exc_info=True)
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "report_error", lang, namespace="query_report"
                ),
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return _DEFAULT_SYSTEM_PROMPT.format(language=context.language or "en")


skill = QueryReportSkill()
