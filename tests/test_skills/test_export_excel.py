"""Tests for export_excel skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.export_excel.handler import (
    ExportExcelSkill,
    _detect_export_type,
    _parse_date_range,
)


def test_skill_attributes():
    skill = ExportExcelSkill()
    assert skill.name == "export_excel"
    assert skill.intents == ["export_excel"]
    assert skill.model == "claude-haiku-4-5"


def test_get_system_prompt(sample_context):
    skill = ExportExcelSkill()
    prompt = skill.get_system_prompt(sample_context)
    lower = prompt.lower()
    assert "export" in lower or "excel" in lower or "spreadsheet" in lower


def test_detect_export_type_from_intent_data():
    assert _detect_export_type({"export_type": "expenses"}, "") == "expenses"
    assert _detect_export_type({"export_type": "tasks"}, "") == "tasks"
    assert _detect_export_type({"export_type": "contacts"}, "") == "contacts"


def test_detect_export_type_from_message():
    assert _detect_export_type({}, "export my tasks") == "tasks"
    assert _detect_export_type({}, "скачай контакты") == "contacts"
    assert _detect_export_type({}, "export expenses") == "expenses"
    assert _detect_export_type({}, "download data") == "expenses"  # default


def test_parse_date_range_defaults():
    from datetime import date

    today = date.today()
    d_from, d_to = _parse_date_range({})
    assert d_from == date(today.year, today.month, 1)
    assert d_to == today


def test_parse_date_range_week():
    from datetime import date, timedelta

    today = date.today()
    d_from, d_to = _parse_date_range({"period": "week"})
    assert d_from == today - timedelta(days=7)
    assert d_to == today


def test_parse_date_range_custom():
    d_from, d_to = _parse_date_range(
        {"date_from": "2025-01-01", "date_to": "2025-01-31"}
    )
    assert str(d_from) == "2025-01-01"
    assert str(d_to) == "2025-01-31"


@patch("src.skills.export_excel.handler.async_session")
async def test_export_expenses_no_data(mock_session, sample_context, text_message):
    """When no transactions, return 'No data found'."""
    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = ExportExcelSkill()
    result = await skill.execute(text_message, sample_context, {})
    assert "no data" in result.response_text.lower()


@patch("src.skills.export_excel.handler.async_session")
async def test_export_expenses_with_data(mock_session, sample_context, text_message):
    """When transactions exist, return xlsx bytes."""
    from datetime import date
    from decimal import Decimal

    mock_tx = MagicMock()
    mock_tx.date = date(2025, 1, 15)
    mock_tx.merchant = "Shell"
    mock_tx.category = "Fuel"
    mock_tx.amount = Decimal("50.00")
    mock_tx.description = "Diesel"

    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_tx]
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = ExportExcelSkill()
    result = await skill.execute(text_message, sample_context, {})
    assert result.response_text
    assert "export" in result.response_text.lower()
    assert result.document is not None
    assert result.document_name.endswith(".xlsx")


@patch("src.skills.export_excel.handler.async_session")
async def test_export_tasks(mock_session, sample_context, text_message):
    """Export tasks returns xlsx with task data."""
    from datetime import datetime

    mock_task = MagicMock()
    mock_task.title = "Buy groceries"
    mock_task.status = MagicMock(value="pending")
    mock_task.due_at = None
    mock_task.created_at = datetime(2025, 1, 10)
    mock_task.description = "Weekly shopping"

    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_task]
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = ExportExcelSkill()
    result = await skill.execute(
        text_message, sample_context, {"export_type": "tasks"}
    )
    assert result.document is not None
    assert result.document_name == "tasks.xlsx"


@patch("src.skills.export_excel.handler.async_session")
async def test_export_contacts(mock_session, sample_context, text_message):
    """Export contacts returns xlsx with contact data."""
    mock_contact = MagicMock()
    mock_contact.name = "John Doe"
    mock_contact.phone = "+1234567890"
    mock_contact.email = "john@example.com"
    mock_contact.role = "client"
    mock_contact.notes = "Regular client"

    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_contact]
    mock_sess.execute = AsyncMock(return_value=mock_result)
    mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
    mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

    skill = ExportExcelSkill()
    result = await skill.execute(
        text_message, sample_context, {"export_type": "contacts"}
    )
    assert result.document is not None
    assert result.document_name == "contacts.xlsx"
