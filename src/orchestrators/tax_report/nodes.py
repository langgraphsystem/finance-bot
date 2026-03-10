"""Tax report orchestrator nodes.

Graph structure (parallel collectors → analysis → calculation → PDF)::

    START ──┬── collect_income ────────┐
            ├── collect_expenses ──────┤
            ├── collect_recurring ─────┼──► analyze_deductions → calculate_tax → generate_pdf → END
            └── collect_mileage ───────┘
"""

import asyncio
import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.orchestrators.resilience import with_timeout
from src.orchestrators.tax_report.deductions import (
    BRACKETS_2026_SINGLE,
    DEDUCTIBLE_CATEGORIES,
    DEDUCTION_TYPE_LABELS,
    QBI_PHASEOUT_END_SINGLE,
    QBI_PHASEOUT_START_SINGLE,
    QBI_RATE,
    SE_DEDUCTION_FACTOR,
    SE_NET_FACTOR,
    SE_TAX_RATE,
)
from src.orchestrators.tax_report.state import TaxReportState

logger = logging.getLogger(__name__)


def _period_dates(year: int, quarter: int | None) -> tuple[date, date]:
    """Return (start, end) for a year or quarter."""
    if quarter is None:
        return date(year, 1, 1), date(year + 1, 1, 1)
    start_month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
    end_month = {1: 4, 2: 7, 3: 10, 4: 1}[quarter]
    end_year = year + 1 if quarter == 4 else year
    return date(year, start_month, 1), date(end_year, end_month, 1)


@with_timeout(10)
@observe(name="tax_collect_income")
async def collect_income(state: TaxReportState) -> TaxReportState:
    """Collect total gross income for the period."""
    family_id = state.get("family_id", "")
    year = state.get("year", date.today().year)
    quarter = state.get("quarter")
    start, end = _period_dates(year, quarter)

    async with async_session() as session:
        stmt = select(func.sum(Transaction.amount)).where(
            Transaction.family_id == uuid.UUID(family_id),
            Transaction.type == TransactionType.income,
            Transaction.date >= start,
            Transaction.date < end,
        )
        total = await session.scalar(stmt)

    return {**state, "gross_income": float(total or 0)}


@with_timeout(10)
@observe(name="tax_collect_expenses")
async def collect_expenses(state: TaxReportState) -> TaxReportState:
    """Collect expenses by category with deductibility flags."""
    family_id = state.get("family_id", "")
    year = state.get("year", date.today().year)
    quarter = state.get("quarter")
    start, end = _period_dates(year, quarter)

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

    expenses: list[dict[str, Any]] = []
    for r in rows:
        cat = r.category
        amount = float(r.total or 0)
        deduction_info = DEDUCTIBLE_CATEGORIES.get(cat)
        is_deductible = deduction_info is not None and deduction_info[1] > 0
        deductible_amount = amount * deduction_info[1] if deduction_info else 0.0
        deduction_type = deduction_info[0] if deduction_info else None

        expenses.append({
            "category": cat,
            "amount": amount,
            "is_deductible": is_deductible,
            "deductible_amount": deductible_amount,
            "deduction_type": deduction_type,
        })

    return {**state, "expenses_by_category": expenses}


@with_timeout(10)
@observe(name="tax_collect_recurring")
async def collect_recurring(state: TaxReportState) -> TaxReportState:
    """Collect active recurring payments (subscription/rent signals)."""
    family_id = state.get("family_id", "")

    try:
        from src.core.models.recurring_payment import RecurringPayment

        async with async_session() as session:
            stmt = select(RecurringPayment).where(
                RecurringPayment.family_id == uuid.UUID(family_id),
                RecurringPayment.is_active == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            payments = result.scalars().all()

        recurring = [
            {
                "name": p.name,
                "amount": float(p.amount),
                "frequency": getattr(p, "frequency", "monthly"),
            }
            for p in payments
        ]
    except Exception as e:
        logger.warning("collect_recurring: %s", e)
        recurring = []

    return {**state, "recurring_payments": recurring}


@with_timeout(10)
@observe(name="tax_collect_mileage")
async def collect_mileage(state: TaxReportState) -> TaxReportState:
    """Collect transport/taxi spend as a proxy for mileage estimation."""
    family_id = state.get("family_id", "")
    year = state.get("year", date.today().year)
    quarter = state.get("quarter")
    start, end = _period_dates(year, quarter)

    transport_categories = {"Транспорт", "Такси"}

    async with async_session() as session:
        stmt = (
            select(func.sum(Transaction.amount))
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.type == TransactionType.expense,
                Category.name.in_(transport_categories),
                Transaction.date >= start,
                Transaction.date < end,
            )
        )
        total = await session.scalar(stmt)

    transport_spend = float(total or 0)
    # Rough proxy: $0.30/mile average fuel/rideshare cost → convert to miles
    mileage_miles = transport_spend / 0.30 if transport_spend > 0 else 0.0

    return {**state, "mileage_miles": mileage_miles}


@with_timeout(30)
@observe(name="tax_analyze_deductions")
async def analyze_deductions(state: TaxReportState) -> TaxReportState:
    """Use Claude Haiku to identify edge-case deductions and missed write-offs."""
    expenses = state.get("expenses_by_category", [])
    recurring = state.get("recurring_payments", [])
    gross_income = state.get("gross_income", 0)
    lang = state.get("language", "en")

    # Compute totals from collected data
    total_deductible = sum(e.get("deductible_amount", 0.0) for e in expenses)
    deduction_breakdown: list[dict] = []
    seen_types: dict[str, float] = {}
    for e in expenses:
        if e.get("is_deductible") and e.get("deduction_type"):
            dt = e["deduction_type"]
            seen_types[dt] = seen_types.get(dt, 0) + e.get("deductible_amount", 0.0)

    for dt, amount in seen_types.items():
        deduction_breakdown.append({
            "label": DEDUCTION_TYPE_LABELS.get(dt, dt),
            "amount": amount,
            "type": dt,
        })

    # Ask LLM for any missed deductions based on expense patterns
    expense_summary = "\n".join(
        f"- {e['category']}: ${e['amount']:.0f}" for e in expenses[:15]
    )
    recurring_summary = "\n".join(
        f"- {r['name']}: ${r['amount']:.0f}/{r.get('frequency', 'mo')}"
        for r in recurring[:10]
    )

    system = (
        "You are a US tax advisor analyzing self-employed deductions. "
        "Given expense categories and recurring payments, identify any commonly missed "
        "deductions. Be concise. List 2-4 specific missed deductions as short bullet points. "
        "Only mention real IRS-recognized deductions applicable to self-employed filers."
    )
    prompt = (
        f"Gross income: ${gross_income:.0f}\n"
        f"Expenses:\n{expense_summary or 'None'}\n"
        f"Recurring payments:\n{recurring_summary or 'None'}\n"
        f"Already identified deductions: {list(seen_types.keys())}\n"
        f"Language: {lang}\n"
        "What common deductions might be missed?"
    )

    try:
        ai_response = await generate_text(
            model="claude-haiku-4-5",
            system=system,
            prompt=prompt,
            max_tokens=300,
        )
        # Extract bullet points
        additional = [
            line.lstrip("- •*").strip()
            for line in ai_response.splitlines()
            if line.strip().startswith(("-", "•", "*"))
        ][:4]
    except Exception as e:
        logger.warning("analyze_deductions LLM call failed: %s", e)
        additional = []

    return {
        **state,
        "total_deductible": total_deductible,
        "deduction_breakdown": deduction_breakdown,
        "additional_deductions": additional,
    }


@observe(name="tax_calculate")
async def calculate_tax(state: TaxReportState) -> TaxReportState:
    """Deterministic tax calculation — no LLM."""
    gross_income = state.get("gross_income", 0.0)
    total_deductible = state.get("total_deductible", 0.0)
    quarter = state.get("quarter")

    # Net profit after deductible expenses
    net_profit = max(gross_income - total_deductible, 0.0)

    # 1. Self-employment tax (15.3% on 92.35% of net profit)
    se_base = net_profit * SE_NET_FACTOR
    se_tax = se_base * SE_TAX_RATE

    # 2. SE deduction (50% of SE tax, above-the-line)
    se_deduction = se_tax * SE_DEDUCTION_FACTOR

    # 3. Adjusted income after SE deduction
    adjusted_income = net_profit - se_deduction

    # 4. QBI deduction §199A (20% of QBI, permanent post July 4, 2025)
    qbi_deduction = 0.0
    if adjusted_income < QBI_PHASEOUT_START_SINGLE:
        qbi_deduction = adjusted_income * QBI_RATE
    elif adjusted_income < QBI_PHASEOUT_END_SINGLE:
        # Phase-out: linear reduction from 20% to 0%
        phase_range = QBI_PHASEOUT_END_SINGLE - QBI_PHASEOUT_START_SINGLE
        reduction = (adjusted_income - QBI_PHASEOUT_START_SINGLE) / phase_range
        qbi_deduction = adjusted_income * QBI_RATE * (1 - reduction)
    # else: no QBI deduction above phase-out end

    # 5. Taxable income for income tax brackets
    taxable = max(adjusted_income - qbi_deduction, 0.0)

    # 6. Income tax from 2026 brackets
    income_tax = _apply_brackets(taxable)

    # 7. Total tax
    total_tax = se_tax + income_tax

    # 8. Effective rate
    effective_rate = (total_tax / gross_income * 100) if gross_income > 0 else 0.0

    # 9. Quarterly safe harbor payment
    if quarter is not None:
        quarterly_payment = total_tax / 4
    else:
        # Annual → show per-quarter estimate
        quarterly_payment = total_tax / 4

    return {
        **state,
        "net_profit": net_profit,
        "se_tax": se_tax,
        "se_deduction": se_deduction,
        "qbi_deduction": qbi_deduction,
        "income_tax": income_tax,
        "total_tax": total_tax,
        "effective_rate": effective_rate,
        "quarterly_payment": quarterly_payment,
    }


def _apply_brackets(taxable: float) -> float:
    """Apply 2026 US federal income tax brackets (single filer)."""
    if taxable <= 0:
        return 0.0
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in BRACKETS_2026_SINGLE:
        bracket_size = min(taxable, limit) - prev_limit
        if bracket_size <= 0:
            break
        tax += bracket_size * rate
        prev_limit = limit
        if taxable <= limit:
            break
    return tax


@with_timeout(20)
@observe(name="tax_generate_pdf")
async def generate_pdf(state: TaxReportState) -> TaxReportState:
    """Generate a PDF tax report using WeasyPrint."""
    try:
        html = _build_html_report(state)
        pdf_bytes = await asyncio.to_thread(_html_to_pdf, html)
    except Exception as e:
        logger.warning("PDF generation failed: %s — sending text only", e)
        pdf_bytes = None

    response_text = _build_response_text(state)
    return {**state, "pdf_bytes": pdf_bytes, "response_text": response_text}


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML to PDF bytes (blocking — run in thread)."""
    from weasyprint import HTML  # type: ignore[import]

    return HTML(string=html).write_pdf()


def _build_html_report(state: TaxReportState) -> str:
    """Build a tax report HTML for WeasyPrint."""
    year = state.get("year", date.today().year)
    quarter = state.get("quarter")
    period = f"Q{quarter} {year}" if quarter else f"Full Year {year}"
    currency = state.get("currency", "USD")
    gross = state.get("gross_income", 0)
    total_ded = state.get("total_deductible", 0)
    net = state.get("net_profit", 0)
    se_tax = state.get("se_tax", 0)
    se_ded = state.get("se_deduction", 0)
    qbi = state.get("qbi_deduction", 0)
    income_tax = state.get("income_tax", 0)
    total_tax = state.get("total_tax", 0)
    eff = state.get("effective_rate", 0)
    quarterly = state.get("quarterly_payment", 0)

    deduction_rows = "".join(
        f"<tr><td>{d['label']}</td><td>${d['amount']:,.2f}</td></tr>"
        for d in state.get("deduction_breakdown", [])
    )
    expense_rows = "".join(
        f"<tr><td>{e['category']}</td><td>${e['amount']:,.2f}</td>"
        f"<td>{'Yes' if e['is_deductible'] else 'No'}</td>"
        f"<td>${e.get('deductible_amount', 0):,.2f}</td></tr>"
        for e in state.get("expenses_by_category", [])
    )
    additional_html = ""
    if state.get("additional_deductions"):
        items = "".join(f"<li>{a}</li>" for a in state["additional_deductions"])
        additional_html = f"<h3>Potential Missed Deductions</h3><ul>{items}</ul>"

    next_deadlines = {
        1: "April 15",
        2: "June 16",
        3: "September 15",
        4: "January 15 (next year)",
    }
    deadline_note = ""
    if quarter:
        deadline_note = f"<p><b>Q{quarter} estimated payment due:</b> {next_deadlines.get(quarter, 'TBD')}</p>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body {{ font-family: Arial, sans-serif; margin: 40px; color: #222; font-size: 13px; }}
  h1 {{ color: #1a4f8b; border-bottom: 2px solid #1a4f8b; padding-bottom: 8px; }}
  h2 {{ color: #1a4f8b; margin-top: 24px; }}
  h3 {{ color: #444; margin-top: 16px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th {{ background: #1a4f8b; color: white; padding: 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #ddd; }}
  .summary-box {{ background: #f0f5ff; border: 1px solid #1a4f8b; padding: 16px; border-radius: 4px; margin: 16px 0; }}
  .summary-row {{ display: flex; justify-content: space-between; padding: 4px 0; }}
  .summary-row.total {{ font-weight: bold; border-top: 1px solid #1a4f8b; margin-top: 8px; padding-top: 8px; }}
  .disclaimer {{ background: #fff3cd; border: 1px solid #ffc107; padding: 12px; border-radius: 4px; margin-top: 24px; font-size: 11px; }}
</style>
</head>
<body>
<h1>Tax Report — {period}</h1>
<p>Generated: {date.today().strftime("%B %d, %Y")} | Currency: {currency}</p>

<h2>Income &amp; Expenses</h2>
<table>
  <tr><th>Category</th><th>Amount</th><th>Deductible?</th><th>Deductible Amount</th></tr>
  {expense_rows or '<tr><td colspan="4">No expenses recorded</td></tr>'}
</table>

<h2>Deductions (Schedule C)</h2>
<table>
  <tr><th>Type</th><th>Amount</th></tr>
  {deduction_rows or '<tr><td colspan="2">No deductions identified</td></tr>'}
</table>
{additional_html}

<h2>Tax Summary</h2>
<div class="summary-box">
  <div class="summary-row"><span>Gross Income</span><span>${gross:,.2f}</span></div>
  <div class="summary-row"><span>Total Deductions</span><span>−${total_ded:,.2f}</span></div>
  <div class="summary-row"><span>Net Profit</span><span>${net:,.2f}</span></div>
  <div class="summary-row"><span>SE Tax (15.3% × 92.35%)</span><span>${se_tax:,.2f}</span></div>
  <div class="summary-row"><span>SE Deduction (50%)</span><span>−${se_ded:,.2f}</span></div>
  <div class="summary-row"><span>QBI Deduction (§199A, 20%)</span><span>−${qbi:,.2f}</span></div>
  <div class="summary-row"><span>Federal Income Tax</span><span>${income_tax:,.2f}</span></div>
  <div class="summary-row total"><span>TOTAL ESTIMATED TAX</span><span>${total_tax:,.2f}</span></div>
  <div class="summary-row"><span>Effective Rate</span><span>{eff:.1f}%</span></div>
</div>

<h2>Quarterly Estimated Payments</h2>
<p><b>Estimated quarterly payment:</b> ${quarterly:,.2f}</p>
{deadline_note}
<p><i>Safe harbor: pay 100% of prior year tax or 90% of current year (110% if AGI > $150K).</i></p>

<div class="disclaimer">
  <b>⚠️ Disclaimer:</b> This is an estimate only. Not legal, tax, or accounting advice.
  Tax laws vary by state and individual circumstances. Consult a licensed CPA or tax
  professional before filing. QBI deduction made permanent by One Big Beautiful Bill Act
  (July 4, 2025).
</div>
</body>
</html>"""


def _build_response_text(state: TaxReportState) -> str:
    """Build Telegram HTML summary."""
    year = state.get("year", date.today().year)
    quarter = state.get("quarter")
    period = f"Q{quarter} {year}" if quarter else str(year)
    gross = state.get("gross_income", 0)
    total_ded = state.get("total_deductible", 0)
    net = state.get("net_profit", 0)
    se_tax = state.get("se_tax", 0)
    qbi = state.get("qbi_deduction", 0)
    income_tax = state.get("income_tax", 0)
    total_tax = state.get("total_tax", 0)
    eff = state.get("effective_rate", 0)
    quarterly = state.get("quarterly_payment", 0)
    currency = state.get("currency", "$")

    parts = [
        f"<b>📊 Tax Report — {period}</b>\n",
        f"Gross income: <b>{currency} {gross:,.0f}</b>",
        f"Deductions: <b>{currency} {total_ded:,.0f}</b>",
        f"Net profit: <b>{currency} {net:,.0f}</b>",
        "",
        f"SE tax: {currency} {se_tax:,.0f}",
        f"QBI deduction (§199A): −{currency} {qbi:,.0f}",
        f"Income tax: {currency} {income_tax:,.0f}",
        f"<b>Total estimated tax: {currency} {total_tax:,.0f}</b>",
        f"Effective rate: {eff:.1f}%",
        "",
        f"Quarterly payment: <b>{currency} {quarterly:,.0f}</b>",
    ]

    additional = state.get("additional_deductions", [])
    if additional:
        parts.append("\n<b>Missed deductions to review:</b>")
        for a in additional[:3]:
            parts.append(f"• {a}")

    pdf_note = "\n<i>Full PDF report attached above.</i>" if state.get("pdf_bytes") else ""
    parts.append(
        "\n<i>⚠️ Estimate only — not tax advice. Consult a CPA before filing."
        f"{pdf_note}</i>"
    )

    return "\n".join(parts)
