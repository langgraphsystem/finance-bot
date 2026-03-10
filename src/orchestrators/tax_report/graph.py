"""Tax report orchestrator — LangGraph parallel fan-out → analysis → calculation → PDF.

Graph::

    START ──┬── collect_income ────────┐
            ├── collect_expenses ──────┤
            ├── collect_recurring ─────┼──► analyze_deductions → calculate_tax → generate_pdf → END
            └── collect_mileage ───────┘

All four collector nodes run in parallel. After fan-in, analysis,
deterministic tax calculation, and PDF generation run sequentially.
"""

import logging
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.tax_report.nodes import (
    analyze_deductions,
    calculate_tax,
    collect_expenses,
    collect_income,
    collect_mileage,
    collect_recurring,
    generate_pdf,
)
from src.orchestrators.tax_report.state import TaxReportState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_COLLECTORS = [
    "collect_income",
    "collect_expenses",
    "collect_recurring",
    "collect_mileage",
]

_COLLECTOR_FUNCS = {
    "collect_income": collect_income,
    "collect_expenses": collect_expenses,
    "collect_recurring": collect_recurring,
    "collect_mileage": collect_mileage,
}


def _build_tax_graph() -> StateGraph:
    """Build and compile the tax report graph."""
    graph = StateGraph(TaxReportState)

    # Register collector nodes
    for name, fn in _COLLECTOR_FUNCS.items():
        graph.add_node(name, fn)

    # Register sequential analysis nodes
    graph.add_node("analyze_deductions", analyze_deductions)
    graph.add_node("calculate_tax", calculate_tax)
    graph.add_node("generate_pdf", generate_pdf)

    # Fan-out: START → all collectors in parallel
    for name in _COLLECTORS:
        graph.add_edge(START, name)

    # Fan-in: all collectors → analyze_deductions
    for name in _COLLECTORS:
        graph.add_edge(name, "analyze_deductions")

    # Sequential chain
    graph.add_edge("analyze_deductions", "calculate_tax")
    graph.add_edge("calculate_tax", "generate_pdf")
    graph.add_edge("generate_pdf", END)

    return graph.compile()


# Lazy singleton
_tax_graph = None


def _get_tax_graph():
    global _tax_graph
    if _tax_graph is None:
        _tax_graph = _build_tax_graph()
    return _tax_graph


class TaxReportOrchestrator:
    """Full annual/quarterly tax report orchestrator.

    Runs parallel data collection, AI deduction analysis,
    deterministic tax calculation, and PDF generation.
    Produces a detailed tax report distinct from the quick tax_estimate skill.
    """

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        family_id = context.family_id
        if not family_id:
            return SkillResult(
                response_text="Set up your account first to generate tax reports."
            )

        # Resolve period
        today = date.today()
        year = intent_data.get("tax_year") or today.year
        quarter = intent_data.get("tax_quarter")  # None = full year

        logger.info(
            "TaxReportOrchestrator: user=%s year=%s quarter=%s",
            context.user_id, year, quarter,
        )

        initial_state: TaxReportState = {
            "user_id": context.user_id,
            "family_id": family_id,
            "language": context.language or "en",
            "currency": context.currency or "USD",
            "business_type": context.business_type,
            "year": int(year),
            "quarter": int(quarter) if quarter is not None else None,
            "gross_income": 0.0,
            "expenses_by_category": [],
            "recurring_payments": [],
            "mileage_miles": 0.0,
            "total_deductible": 0.0,
            "deduction_breakdown": [],
            "additional_deductions": [],
            "net_profit": 0.0,
            "se_tax": 0.0,
            "se_deduction": 0.0,
            "qbi_deduction": 0.0,
            "income_tax": 0.0,
            "total_tax": 0.0,
            "effective_rate": 0.0,
            "quarterly_payment": 0.0,
            "narrative": "",
            "pdf_bytes": None,
            "response_text": "",
        }

        try:
            result = await _get_tax_graph().ainvoke(initial_state)

            response_text = result.get("response_text", "")
            pdf_bytes = result.get("pdf_bytes")

            period = f"Q{quarter}_{year}" if quarter else str(year)
            filename = f"tax_report_{period}.pdf"

            if pdf_bytes:
                return SkillResult(
                    response_text=response_text,
                    document=pdf_bytes,
                    document_name=filename,
                )
            return SkillResult(response_text=response_text)

        except Exception as e:
            logger.exception("TaxReportOrchestrator failed: %s", e)
            try:
                from src.orchestrators.resilience import save_to_dlq

                await save_to_dlq(
                    graph_name="tax_report",
                    thread_id=f"tax-{context.user_id}-{year}",
                    user_id=context.user_id,
                    family_id=family_id,
                    error=str(e),
                )
            except Exception:
                pass
            return SkillResult(
                response_text=(
                    "Failed to generate tax report. "
                    "Try again or use /tax_estimate for a quick estimate."
                )
            )
