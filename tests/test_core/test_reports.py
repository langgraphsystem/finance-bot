"""Tests for PDF report generation."""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models.enums import LifeEventType
from src.core.reports import generate_monthly_report, render_report_html

# ---------------------------------------------------------------------------
# render_report_html — template rendering (no WeasyPrint needed)
# ---------------------------------------------------------------------------


def test_render_report_html_basic():
    """Render HTML with income, expense, and categories."""
    html = render_report_html(
        title="Финансовый отчёт — Январь 2026",
        period="Январь 2026",
        total_income=5000.0,
        total_expense=3200.0,
        expense_categories=[
            {"name": "Дизель", "icon": "⛽", "total": 2000.0, "percent": 62.5},
            {"name": "Продукты", "icon": "🛒", "total": 1200.0, "percent": 37.5},
        ],
        income_categories=[
            {"name": "Зарплата", "icon": "💰", "total": 5000.0},
        ],
        generated_date="2026-01-31",
    )
    assert "Финансовый отчёт" in html
    assert "Январь 2026" in html
    assert "$5000.00" in html
    assert "$3200.00" in html
    assert "Дизель" in html
    assert "Продукты" in html
    assert "Зарплата" in html
    assert "62.5%" in html
    assert "FinBot" in html


def test_render_report_html_empty_categories():
    """Render HTML with no categories — should not crash."""
    html = render_report_html(
        title="Пустой отчёт",
        period="Февраль 2026",
        total_income=0.0,
        total_expense=0.0,
        expense_categories=[],
        income_categories=[],
        generated_date="2026-02-28",
    )
    assert "Пустой отчёт" in html
    assert "$0.00" in html
    # Category tables should not appear
    assert "Расходы по категориям" not in html
    assert "Доходы по категориям" not in html


def test_render_report_html_balance_calculation():
    """Balance displayed correctly (income - expense)."""
    html = render_report_html(
        title="Тест баланса",
        period="Март 2026",
        total_income=1000.0,
        total_expense=400.0,
        expense_categories=[],
        income_categories=[],
        generated_date="2026-03-31",
    )
    # Balance should be 600.00
    assert "$600.00" in html


def test_render_report_html_with_life_summary():
    """Life summary section renders when data is present."""
    html = render_report_html(
        title="Отчёт с заметками",
        period="Февраль 2026",
        total_income=0.0,
        total_expense=0.0,
        expense_categories=[],
        income_categories=[],
        life_summary={
            "total": 5,
            "by_type": [
                {"icon": "📝", "label": "Заметки", "count": 3},
                {"icon": "☕", "label": "Напитки", "count": 2},
            ],
            "recent": [
                {"date": "15.02", "icon": "📝", "text": "Тестовая заметка", "tags": "#test"},
            ],
        },
        generated_date="2026-02-28",
    )
    assert "Записи и заметки" in html
    assert "Заметки" in html
    assert "Напитки" in html
    assert "Тестовая заметка" in html
    assert "#test" in html
    assert "Всего записей" in html


def test_render_report_html_without_life_summary():
    """No life summary section when life_summary is None."""
    html = render_report_html(
        title="Без заметок",
        period="Февраль 2026",
        total_income=0.0,
        total_expense=0.0,
        expense_categories=[],
        income_categories=[],
        life_summary=None,
        generated_date="2026-02-28",
    )
    assert "Записи и заметки" not in html


# ---------------------------------------------------------------------------
# generate_monthly_report — full pipeline with mocked DB + WeasyPrint
# ---------------------------------------------------------------------------


def _mock_db_results(expense_rows, total_expense, income_rows, total_income, life_events=None):
    """Create mock DB session that returns given data on sequential execute calls."""
    expense_result = MagicMock()
    expense_result.all.return_value = expense_rows

    total_exp_result = MagicMock()
    total_exp_result.scalar.return_value = total_expense

    income_result = MagicMock()
    income_result.all.return_value = income_rows

    total_inc_result = MagicMock()
    total_inc_result.scalar.return_value = total_income

    life_result = MagicMock()
    life_scalars = MagicMock()
    life_scalars.all.return_value = life_events or []
    life_result.scalars.return_value = life_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[expense_result, total_exp_result, income_result, total_inc_result, life_result]
    )

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_session_ctx


@pytest.mark.asyncio
async def test_generate_monthly_report_with_data():
    """generate_monthly_report returns PDF bytes and correct filename."""
    family_id = str(uuid.uuid4())
    mock_session_ctx = _mock_db_results(
        expense_rows=[("Дизель", "⛽", Decimal("1500.00"))],
        total_expense=Decimal("1500.00"),
        income_rows=[("Зарплата", "💰", Decimal("5000.00"))],
        total_income=Decimal("5000.00"),
    )

    fake_pdf = b"%PDF-1.4 fake content"

    with (
        patch("src.core.reports.async_session", return_value=mock_session_ctx),
        patch("src.core.reports.html_to_pdf", return_value=fake_pdf) as mock_to_pdf,
    ):
        pdf_bytes, filename = await generate_monthly_report(family_id=family_id, year=2026, month=1)

    assert pdf_bytes == fake_pdf
    assert filename == "report_2026_01.pdf"

    # Verify HTML content passed to html_to_pdf
    mock_to_pdf.assert_called_once()
    rendered_html = mock_to_pdf.call_args[0][0]
    assert "Дизель" in rendered_html
    assert "Зарплата" in rendered_html
    assert "Январь 2026" in rendered_html


@pytest.mark.asyncio
async def test_generate_monthly_report_empty_data():
    """Empty data does not crash — returns valid PDF bytes."""
    family_id = str(uuid.uuid4())
    mock_session_ctx = _mock_db_results(
        expense_rows=[],
        total_expense=None,
        income_rows=[],
        total_income=None,
    )

    fake_pdf = b"%PDF-1.4 empty"

    with (
        patch("src.core.reports.async_session", return_value=mock_session_ctx),
        patch("src.core.reports.html_to_pdf", return_value=fake_pdf) as mock_to_pdf,
    ):
        pdf_bytes, filename = await generate_monthly_report(family_id=family_id, year=2026, month=2)

    assert pdf_bytes == fake_pdf
    assert filename == "report_2026_02.pdf"

    # Template should not contain category tables
    rendered_html = mock_to_pdf.call_args[0][0]
    assert "Расходы по категориям" not in rendered_html
    assert "$0.00" in rendered_html


@pytest.mark.asyncio
async def test_generate_monthly_report_defaults_to_current_month():
    """When year/month are None, defaults to current date."""
    family_id = str(uuid.uuid4())
    mock_session_ctx = _mock_db_results(
        expense_rows=[],
        total_expense=None,
        income_rows=[],
        total_income=None,
    )

    fake_pdf = b"%PDF"
    today = date.today()

    with (
        patch("src.core.reports.async_session", return_value=mock_session_ctx),
        patch("src.core.reports.html_to_pdf", return_value=fake_pdf),
    ):
        pdf_bytes, filename = await generate_monthly_report(family_id=family_id)

    expected_filename = f"report_{today.year}_{today.month:02d}.pdf"
    assert filename == expected_filename
    assert isinstance(pdf_bytes, bytes)


@pytest.mark.asyncio
async def test_generate_monthly_report_december_boundary():
    """December report correctly sets end_date to January of next year."""
    family_id = str(uuid.uuid4())
    mock_session_ctx = _mock_db_results(
        expense_rows=[],
        total_expense=None,
        income_rows=[],
        total_income=None,
    )

    fake_pdf = b"%PDF"

    with (
        patch("src.core.reports.async_session", return_value=mock_session_ctx),
        patch("src.core.reports.html_to_pdf", return_value=fake_pdf) as mock_to_pdf,
    ):
        pdf_bytes, filename = await generate_monthly_report(
            family_id=family_id, year=2025, month=12
        )

    assert filename == "report_2025_12.pdf"
    rendered_html = mock_to_pdf.call_args[0][0]
    assert "Декабрь 2025" in rendered_html


@pytest.mark.asyncio
async def test_generate_monthly_report_includes_life_events():
    """Life events from the period appear in the rendered report."""
    family_id = str(uuid.uuid4())

    # Create mock life events
    mock_event = MagicMock()
    mock_event.type = LifeEventType.note
    mock_event.date = date(2026, 1, 10)
    mock_event.text = "Важная заметка для отчёта"
    mock_event.tags = ["work"]
    mock_event.created_at = None

    mock_session_ctx = _mock_db_results(
        expense_rows=[("Топливо", "⛽", Decimal("500.00"))],
        total_expense=Decimal("500.00"),
        income_rows=[],
        total_income=None,
        life_events=[mock_event],
    )

    fake_pdf = b"%PDF-life"

    with (
        patch("src.core.reports.async_session", return_value=mock_session_ctx),
        patch("src.core.reports.html_to_pdf", return_value=fake_pdf) as mock_to_pdf,
    ):
        pdf_bytes, filename = await generate_monthly_report(family_id=family_id, year=2026, month=1)

    assert pdf_bytes == fake_pdf
    rendered_html = mock_to_pdf.call_args[0][0]
    assert "Записи и заметки" in rendered_html
    assert "Важная заметка для отчёта" in rendered_html
    assert "#work" in rendered_html
