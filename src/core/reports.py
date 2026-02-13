"""PDF report generation using WeasyPrint + Jinja2."""

import logging
import uuid
from datetime import date

from jinja2 import Environment, BaseLoader
from sqlalchemy import select, func

from src.core.db import async_session
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe

logger = logging.getLogger(__name__)

# HTML template for monthly report
MONTHLY_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        h2 { color: #2980b9; margin-top: 30px; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th { background-color: #3498db; color: white; padding: 10px; text-align: left; }
        td { padding: 8px 10px; border-bottom: 1px solid #ddd; }
        tr:nth-child(even) { background-color: #f2f2f2; }
        .total-row { font-weight: bold; background-color: #ebf5fb !important; }
        .amount { text-align: right; }
        .summary { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .income { color: #27ae60; }
        .expense { color: #e74c3c; }
        .footer { margin-top: 40px; font-size: 0.8em; color: #999; border-top: 1px solid #ddd; padding-top: 10px; }
    </style>
</head>
<body>
    <h1>{{ title }}</h1>
    <p>Период: {{ period }}</p>

    <div class="summary">
        <h2>Итоги</h2>
        <p class="income">Доходы: ${{ "%.2f"|format(total_income) }}</p>
        <p class="expense">Расходы: ${{ "%.2f"|format(total_expense) }}</p>
        <p><strong>Баланс: ${{ "%.2f"|format(total_income - total_expense) }}</strong></p>
    </div>

    {% if expense_categories %}
    <h2>Расходы по категориям</h2>
    <table>
        <tr><th>Категория</th><th class="amount">Сумма</th><th class="amount">%</th></tr>
        {% for cat in expense_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
            <td class="amount">{{ "%.1f"|format(cat.percent) }}%</td>
        </tr>
        {% endfor %}
        <tr class="total-row">
            <td>Итого</td>
            <td class="amount">${{ "%.2f"|format(total_expense) }}</td>
            <td class="amount">100%</td>
        </tr>
    </table>
    {% endif %}

    {% if income_categories %}
    <h2>Доходы по категориям</h2>
    <table>
        <tr><th>Категория</th><th class="amount">Сумма</th></tr>
        {% for cat in income_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    <div class="footer">
        Сгенерировано FinBot | {{ generated_date }}
    </div>
</body>
</html>
"""

MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

jinja_env = Environment(loader=BaseLoader())


def render_report_html(
    *,
    title: str,
    period: str,
    total_income: float,
    total_expense: float,
    expense_categories: list[dict],
    income_categories: list[dict],
    generated_date: str,
) -> str:
    """Render the monthly report HTML from template and data."""
    template = jinja_env.from_string(MONTHLY_REPORT_TEMPLATE)
    return template.render(
        title=title,
        period=period,
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        generated_date=generated_date,
    )


@observe(name="generate_report")
async def generate_monthly_report(
    family_id: str,
    year: int | None = None,
    month: int | None = None,
) -> tuple[bytes, str]:
    """Generate a monthly PDF report.

    Returns:
        Tuple of (pdf_bytes, filename).
    """
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    async with async_session() as session:
        # Get expenses by category
        expense_result = await session.execute(
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        expense_rows = expense_result.all()

        # Get total expense
        total_exp_result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.expense,
            )
        )
        total_expense = float(total_exp_result.scalar() or 0)

        # Get income by category
        income_result = await session.execute(
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.income,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        income_rows = income_result.all()

        # Get total income
        total_inc_result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.type == TransactionType.income,
            )
        )
        total_income = float(total_inc_result.scalar() or 0)

    # Format categories with percentages
    expense_categories = []
    for name, icon, total in expense_rows:
        expense_categories.append({
            "name": name,
            "icon": icon or "",
            "total": float(total),
            "percent": (float(total) / total_expense * 100) if total_expense > 0 else 0,
        })

    income_categories = []
    for name, icon, total in income_rows:
        income_categories.append({
            "name": name,
            "icon": icon or "",
            "total": float(total),
        })

    # Render HTML
    html_content = render_report_html(
        title=f"Финансовый отчёт — {MONTH_NAMES[month]} {year}",
        period=f"{MONTH_NAMES[month]} {year}",
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        generated_date=today.isoformat(),
    )

    # Generate PDF
    pdf_bytes = html_to_pdf(html_content)
    filename = f"report_{year}_{month:02d}.pdf"

    return pdf_bytes, filename


def html_to_pdf(html_content: str) -> bytes:
    """Convert an HTML string to PDF bytes using WeasyPrint.

    Separated into its own function to allow easy mocking in tests
    (WeasyPrint requires system libraries that may not be available in CI).
    """
    from weasyprint import HTML  # lazy import — requires system GTK/Pango libs

    return HTML(string=html_content).write_pdf()
