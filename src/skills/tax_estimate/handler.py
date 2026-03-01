"""Tax estimate skill — quarterly tax estimation from transaction data.

Tax consultant specialist: calculates estimated quarterly taxes based on
actual income and deductible expenses. Supports self-employment tax.
"""

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

TAX_SYSTEM_PROMPT = """\
You are a tax estimation assistant. Provide quarterly tax estimates
based on actual income and expense data from the user's records.
You receive READY data from SQL. NEVER calculate yourself — use the numbers provided.
Always include this disclaimer: "This is an estimate, not professional tax advice. \
Consult a CPA for your specific situation."
Format with HTML tags for Telegram. Use <b>bold</b> for key amounts.
Structure: gross income → deductible expenses → net profit → estimated tax.
If business_type is set, include self-employment tax (15.3% on 92.35% of net)."""

# US quarterly tax deadlines
QUARTERLY_DEADLINES = {
    1: "April 15",
    2: "June 15",
    3: "September 15",
    4: "January 15 (next year)",
}


def _current_quarter() -> int:
    """Return current quarter number (1-4)."""
    return (date.today().month - 1) // 3 + 1


def _quarter_date_range(quarter: int, year: int | None = None) -> tuple[date, date]:
    """Return (start, end) dates for a quarter."""
    y = year or date.today().year
    start_months = {1: 1, 2: 4, 3: 7, 4: 10}
    end_months = {1: 4, 2: 7, 3: 10, 4: 1}
    start = date(y, start_months[quarter], 1)
    end_year = y + 1 if quarter == 4 else y
    end = date(end_year, end_months[quarter], 1)
    return start, end


class TaxEstimateSkill:
    name = "tax_estimate"
    intents = ["tax_estimate"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        return TAX_SYSTEM_PROMPT

    @observe(name="skill_tax_estimate")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        family_id = context.family_id
        if not family_id:
            return SkillResult(response_text="Set up your account first to get tax estimates.")

        # Deep agent path for complex tax requests (feature-flagged)
        from src.core.config import settings

        if settings.ff_deep_agents:
            from src.core.deep_agent.classifier import (
                ComplexityLevel,
                classify_tax_complexity,
            )

            user_text = message.text or ""
            complexity = classify_tax_complexity(user_text)
            if complexity == ComplexityLevel.complex:
                logger.info("tax_estimate: routing to deep agent (complex)")
                return await self._execute_deep(message, context, intent_data)

        quarter = _current_quarter()
        year = date.today().year
        start, end = _quarter_date_range(quarter, year)

        # If we're early in the quarter with no data, show previous quarter
        today = date.today()
        if (today - start).days < 7:
            prev_q = quarter - 1 if quarter > 1 else 4
            prev_y = year if quarter > 1 else year - 1
            alt_start, alt_end = _quarter_date_range(prev_q, prev_y)
            alt_income = await self._get_total(family_id, alt_start, alt_end, "income")
            if alt_income > 0:
                quarter, year = prev_q, prev_y
                start, end = alt_start, alt_end

        # Fetch data
        gross_income = await self._get_total(family_id, start, end, "income")
        total_expenses = await self._get_total(family_id, start, end, "expense")
        expense_breakdown = await self._get_expense_categories(family_id, start, end)

        if gross_income == 0 and total_expenses == 0:
            return SkillResult(
                response_text=f"No income or expenses recorded for Q{quarter} {year}. "
                "Start tracking transactions to get tax estimates."
            )

        # Estimate taxes
        net_profit = gross_income - total_expenses
        is_business = bool(context.business_type)

        # Self-employment tax (if business)
        se_tax = 0.0
        if is_business and net_profit > 0:
            se_base = net_profit * 0.9235  # 92.35% of net
            se_tax = se_base * 0.153  # 15.3% SE tax

        # Simplified income tax estimate (marginal rates)
        income_tax = self._estimate_income_tax(net_profit * 4)  # Annualize
        quarterly_income_tax = income_tax / 4

        total_estimated = quarterly_income_tax + se_tax
        deadline = QUARTERLY_DEADLINES.get(quarter, "")

        # Build data context for LLM
        data_lines = [
            f"Quarter: Q{quarter} {year} ({start.isoformat()} to {end.isoformat()})",
            f"Deadline: {deadline}",
            f"Currency: {context.currency}",
            f"Business type: {context.business_type or 'personal'}",
            f"\nGross income: {gross_income:.2f}",
            f"Total expenses: {total_expenses:.2f}",
            f"Net profit: {net_profit:.2f}",
        ]

        if expense_breakdown:
            data_lines.append("\nDeductible expenses by category:")
            for cat in expense_breakdown[:10]:
                data_lines.append(f"  {cat['category']}: {cat['amount']:.2f}")

        data_lines.append(f"\nEstimated quarterly income tax: {quarterly_income_tax:.2f}")
        if se_tax > 0:
            data_lines.append(f"Self-employment tax: {se_tax:.2f}")
        data_lines.append(f"Total estimated payment: {total_estimated:.2f}")

        data_text = "\n".join(data_lines)

        assembled = intent_data.get("_assembled")
        model = intent_data.get("_model", self.model)
        response = await generate_text(
            model=model,
            system_prompt=TAX_SYSTEM_PROMPT,
            user_message=f"{message.text}\n\n--- DATA ---\n{data_text}",
            assembled_context=assembled,
        )

        return SkillResult(response_text=response)

    @staticmethod
    async def _get_total(
        family_id: str,
        start: date,
        end: date,
        tx_type: str,
    ) -> float:
        """Get total income or expenses for a period."""
        tt = TransactionType.income if tx_type == "income" else TransactionType.expense
        async with async_session() as session:
            stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.type == tt,
                Transaction.date >= start,
                Transaction.date < end,
            )
            result = await session.scalar(stmt)
            return float(result or 0)

    @staticmethod
    async def _get_expense_categories(
        family_id: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Get expense breakdown by category."""
        async with async_session() as session:
            stmt = (
                select(
                    Category.name.label("category"),
                    func.sum(Transaction.amount).label("total"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.expense,
                    Transaction.date >= start,
                    Transaction.date < end,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount).desc())
            )
            rows = (await session.execute(stmt)).all()
            return [{"category": r.category, "amount": float(r.total or 0)} for r in rows]

    @staticmethod
    def _estimate_income_tax(annual_income: float) -> float:
        """Simplified US federal income tax estimate (2026 brackets, single filer)."""
        if annual_income <= 0:
            return 0.0

        brackets = [
            (11_600, 0.10),
            (47_150 - 11_600, 0.12),
            (100_525 - 47_150, 0.22),
            (191_950 - 100_525, 0.24),
            (243_725 - 191_950, 0.32),
            (609_350 - 243_725, 0.35),
            (float("inf"), 0.37),
        ]

        tax = 0.0
        remaining = annual_income
        for bracket_size, rate in brackets:
            taxable = min(remaining, bracket_size)
            tax += taxable * rate
            remaining -= taxable
            if remaining <= 0:
                break
        return tax

    async def _execute_deep(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route complex tax requests to the deep agent orchestrator."""
        from src.orchestrators.deep_agent.graph import DeepAgentOrchestrator

        family_id = context.family_id
        year = date.today().year

        # Collect financial data for all quarters
        financial_data: dict[str, Any] = {
            "year": year,
            "currency": context.currency,
            "business_type": context.business_type or "personal",
            "quarters": {},
        }

        for q in range(1, 5):
            start, end = _quarter_date_range(q, year)
            income = await self._get_total(family_id, start, end, "income")
            expenses = await self._get_total(family_id, start, end, "expense")
            cats = await self._get_expense_categories(family_id, start, end)
            financial_data["quarters"][f"Q{q}"] = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "gross_income": income,
                "total_expenses": expenses,
                "net_profit": income - expenses,
                "expense_categories": cats[:10],
            }

        # Annual totals
        annual_income = sum(q["gross_income"] for q in financial_data["quarters"].values())
        annual_expenses = sum(q["total_expenses"] for q in financial_data["quarters"].values())
        financial_data["annual"] = {
            "gross_income": annual_income,
            "total_expenses": annual_expenses,
            "net_profit": annual_income - annual_expenses,
            "estimated_tax": self._estimate_income_tax(annual_income - annual_expenses),
        }

        if context.business_type and (annual_income - annual_expenses) > 0:
            se_base = (annual_income - annual_expenses) * 0.9235
            financial_data["annual"]["self_employment_tax"] = se_base * 0.153

        orchestrator = DeepAgentOrchestrator()
        return await orchestrator.run(
            task_description=message.text or "Generate detailed annual tax report",
            skill_type="tax_report",
            user_id=context.user_id,
            family_id=context.family_id,
            language=context.language or "en",
            model=self.model,
            financial_data=financial_data,
        )


skill = TaxEstimateSkill()
