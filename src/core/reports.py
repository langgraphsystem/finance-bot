"""PDF report generation using WeasyPrint + Jinja2."""

import asyncio
import logging
import uuid
from collections import Counter
from datetime import date

from jinja2 import BaseLoader, Environment
from sqlalchemy import func, select

from src.core.db import async_session
from src.core.models.category import Category
from src.core.models.enums import LifeEventType, TransactionType
from src.core.models.life_event import LifeEvent
from src.core.models.transaction import Transaction
from src.core.observability import observe

logger = logging.getLogger(__name__)

# HTML template for monthly report (with Jinja2 label variables)
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
        .footer { margin-top: 40px; font-size: 0.8em; color: #999;
                  border-top: 1px solid #ddd; padding-top: 10px; }
    </style>
</head>
<body>
    <h1>{{ title }}</h1>
    <p>{{ labels.period }}: {{ period }}</p>

    <div class="summary">
        <h2>{{ labels.summary }}</h2>
        <p class="income">{{ labels.income }}: ${{ "%.2f"|format(total_income) }}</p>
        <p class="expense">{{ labels.expenses }}: ${{ "%.2f"|format(total_expense) }}</p>
        <p><strong>{{ labels.balance }}:
        ${{ "%.2f"|format(total_income - total_expense) }}</strong></p>
    </div>

    {% if expense_categories %}
    <h2>{{ labels.expenses_by_category }}</h2>
    <table>
        <tr><th>{{ labels.category }}</th>
        <th class="amount">{{ labels.amount }}</th>
        <th class="amount">%</th></tr>
        {% for cat in expense_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
            <td class="amount">{{ "%.1f"|format(cat.percent) }}%</td>
        </tr>
        {% endfor %}
        <tr class="total-row">
            <td>{{ labels.total }}</td>
            <td class="amount">${{ "%.2f"|format(total_expense) }}</td>
            <td class="amount">100%</td>
        </tr>
    </table>
    {% endif %}

    {% if income_categories %}
    <h2>{{ labels.income_by_category }}</h2>
    <table>
        <tr><th>{{ labels.category }}</th><th class="amount">{{ labels.amount }}</th></tr>
        {% for cat in income_categories %}
        <tr>
            <td>{{ cat.icon }} {{ cat.name }}</td>
            <td class="amount">${{ "%.2f"|format(cat.total) }}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    {% if life_summary %}
    <h2>{{ labels.life_entries }}</h2>
    <div class="summary">
        <p><strong>{{ labels.total_entries }}:</strong> {{ life_summary.total }}</p>
        {% if life_summary.by_type %}
        <table>
            <tr><th>{{ labels.type }}</th><th class="amount">{{ labels.count }}</th></tr>
            {% for item in life_summary.by_type %}
            <tr>
                <td>{{ item.icon }} {{ item.label }}</td>
                <td class="amount">{{ item.count }}</td>
            </tr>
            {% endfor %}
        </table>
        {% endif %}
        {% if life_summary.recent %}
        <h3 style="margin-top: 20px;">{{ labels.recent_entries }}</h3>
        {% for event in life_summary.recent %}
        <p style="margin: 4px 0;">
            <span style="color: #999;">{{ event.date }}</span>
            {{ event.icon }} {{ event.text }}
            {% if event.tags %}<span style="color: #3498db;">{{ event.tags }}</span>{% endif %}
        </p>
        {% endfor %}
        {% endif %}
    </div>
    {% endif %}

    <div class="footer">
        {{ labels.generated_by }} | {{ generated_date }}
    </div>
</body>
</html>
"""

MONTH_NAMES_I18N: dict[str, dict[int, str]] = {
    "en": {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    },
    "ru": {
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
    },
    "es": {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    },
}

MONTH_NAMES = MONTH_NAMES_I18N["ru"]

REPORT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "period": "Period",
        "summary": "Summary",
        "income": "Income",
        "expenses": "Expenses",
        "balance": "Balance",
        "expenses_by_category": "Expenses by Category",
        "income_by_category": "Income by Category",
        "category": "Category",
        "amount": "Amount",
        "total": "Total",
        "life_entries": "Life Entries",
        "total_entries": "Total entries",
        "type": "Type",
        "count": "Count",
        "recent_entries": "Recent Entries",
        "generated_by": "Generated by FinBot",
        "report_title": "Financial Report",
    },
    "ru": {
        "period": "Период",
        "summary": "Итоги",
        "income": "Доходы",
        "expenses": "Расходы",
        "balance": "Баланс",
        "expenses_by_category": "Расходы по категориям",
        "income_by_category": "Доходы по категориям",
        "category": "Категория",
        "amount": "Сумма",
        "total": "Итого",
        "life_entries": "Записи и заметки",
        "total_entries": "Всего записей",
        "type": "Тип",
        "count": "Кол-во",
        "recent_entries": "Последние записи",
        "generated_by": "Сгенерировано FinBot",
        "report_title": "Финансовый отчёт",
    },
    "es": {
        "period": "Periodo",
        "summary": "Resumen",
        "income": "Ingresos",
        "expenses": "Gastos",
        "balance": "Balance",
        "expenses_by_category": "Gastos por categoria",
        "income_by_category": "Ingresos por categoria",
        "category": "Categoria",
        "amount": "Monto",
        "total": "Total",
        "life_entries": "Entradas de vida",
        "total_entries": "Total de entradas",
        "type": "Tipo",
        "count": "Cantidad",
        "recent_entries": "Entradas recientes",
        "generated_by": "Generado por FinBot",
        "report_title": "Informe financiero",
    },
}

_LIFE_TYPE_LABELS_I18N: dict[str, dict] = {
    "en": {
        LifeEventType.note: ("📝", "Notes"),
        LifeEventType.food: ("🍽", "Food"),
        LifeEventType.drink: ("☕", "Drinks"),
        LifeEventType.mood: ("😊", "Mood"),
        LifeEventType.task: ("✅", "Tasks"),
        LifeEventType.reflection: ("🌙", "Reflection"),
    },
    "ru": {
        LifeEventType.note: ("📝", "Заметки"),
        LifeEventType.food: ("🍽", "Питание"),
        LifeEventType.drink: ("☕", "Напитки"),
        LifeEventType.mood: ("😊", "Настроение"),
        LifeEventType.task: ("✅", "Задачи"),
        LifeEventType.reflection: ("🌙", "Рефлексия"),
    },
    "es": {
        LifeEventType.note: ("📝", "Notas"),
        LifeEventType.food: ("🍽", "Comida"),
        LifeEventType.drink: ("☕", "Bebidas"),
        LifeEventType.mood: ("😊", "Estado de animo"),
        LifeEventType.task: ("✅", "Tareas"),
        LifeEventType.reflection: ("🌙", "Reflexion"),
    },
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
    life_summary: dict | None = None,
    generated_date: str,
    language: str = "ru",
) -> str:
    """Render the monthly report HTML from template and data."""
    labels = REPORT_LABELS.get(language, REPORT_LABELS["en"])
    template = jinja_env.from_string(MONTHLY_REPORT_TEMPLATE)
    return template.render(
        title=title,
        period=period,
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        life_summary=life_summary,
        generated_date=generated_date,
        labels=labels,
    )


@observe(name="generate_report")
async def generate_monthly_report(
    family_id: str,
    year: int | None = None,
    month: int | None = None,
    language: str = "ru",
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

        # Get life events for the period
        life_result = await session.execute(
            select(LifeEvent)
            .where(
                LifeEvent.family_id == uuid.UUID(family_id),
                LifeEvent.date >= start_date,
                LifeEvent.date < end_date,
            )
            .order_by(LifeEvent.date.desc())
        )
        life_events = list(life_result.scalars().all())

    # Build life events summary
    life_summary = _build_life_summary(life_events, language) if life_events else None

    # Format categories with percentages
    expense_categories = []
    for name, icon, total in expense_rows:
        expense_categories.append(
            {
                "name": name,
                "icon": icon or "",
                "total": float(total),
                "percent": (float(total) / total_expense * 100) if total_expense > 0 else 0,
            }
        )

    income_categories = []
    for name, icon, total in income_rows:
        income_categories.append(
            {
                "name": name,
                "icon": icon or "",
                "total": float(total),
            }
        )

    # Render HTML
    month_names = MONTH_NAMES_I18N.get(language, MONTH_NAMES_I18N["en"])
    labels = REPORT_LABELS.get(language, REPORT_LABELS["en"])
    report_title = labels["report_title"]
    html_content = render_report_html(
        title=f"{report_title} — {month_names[month]} {year}",
        period=f"{month_names[month]} {year}",
        total_income=total_income,
        total_expense=total_expense,
        expense_categories=expense_categories,
        income_categories=income_categories,
        life_summary=life_summary,
        generated_date=today.isoformat(),
        language=language,
    )

    # Generate PDF (in thread to avoid blocking the event loop)
    pdf_bytes = await asyncio.to_thread(html_to_pdf, html_content)
    filename = f"report_{year}_{month:02d}.pdf"

    return pdf_bytes, filename


_LIFE_TYPE_LABELS = _LIFE_TYPE_LABELS_I18N["ru"]


def _build_life_summary(events: list, language: str = "ru") -> dict:
    """Build a summary dict of life events for the report template."""
    type_counts = Counter(e.type for e in events)
    life_labels = _LIFE_TYPE_LABELS_I18N.get(language, _LIFE_TYPE_LABELS_I18N["en"])

    by_type = []
    for event_type, count in type_counts.most_common():
        icon, label = life_labels.get(event_type, ("📌", str(event_type)))
        by_type.append({"icon": icon, "label": label, "count": count})

    # Recent events (last 10)
    recent = []
    for event in events[:10]:
        icon, _ = life_labels.get(event.type, ("📌", ""))
        text = (event.text or "")[:80]
        if len(event.text or "") > 80:
            text += "..."
        tag_str = ""
        if event.tags:
            tag_str = " ".join(f"#{t}" for t in event.tags)
        recent.append(
            {
                "date": event.date.strftime("%d.%m"),
                "icon": icon,
                "text": text,
                "tags": tag_str,
            }
        )

    return {
        "total": len(events),
        "by_type": by_type,
        "recent": recent,
    }


def html_to_pdf(html_content: str) -> bytes:
    """Convert an HTML string to PDF bytes using WeasyPrint.

    Separated into its own function to allow easy mocking in tests
    (WeasyPrint requires system libraries that may not be available in CI).
    """
    from weasyprint import HTML  # lazy import — requires system GTK/Pango libs

    return HTML(string=html_content).write_pdf()
