"""Tests for export_excel skill."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.export_excel.handler import (
    ExportExcelSkill,
    _detect_export_type,
    _parse_date_range,
)


@pytest.fixture
def skill():
    return ExportExcelSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str = "export to excel") -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def test_skill_attributes(skill):
    assert skill.name == "export_excel"
    assert "export_excel" in skill.intents
    assert skill.model == "claude-haiku-4-5"


def test_get_system_prompt(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    prompt_lower = prompt.lower()
    assert "export" in prompt_lower or "excel" in prompt_lower or "spreadsheet" in prompt_lower


def test_detect_export_type_from_intent_data():
    assert _detect_export_type({"export_type": "tasks"}, "") == "tasks"
    assert _detect_export_type({"export_type": "contacts"}, "") == "contacts"


def test_detect_export_type_from_message():
    assert _detect_export_type({}, "export tasks") == "tasks"
    assert _detect_export_type({}, "экспорт контактов") == "contacts"
    assert _detect_export_type({}, "export my data") == "expenses"


def test_parse_date_range_defaults():
    today = date.today()
    start, end = _parse_date_range({})
    assert start == date(today.year, today.month, 1)
    assert end == today


def test_parse_date_range_week():
    from datetime import timedelta

    today = date.today()
    start, end = _parse_date_range({"period": "week"})
    assert start == today - timedelta(days=7)
    assert end == today


def test_parse_date_range_custom():
    start, end = _parse_date_range({"date_from": "2026-01-01", "date_to": "2026-01-31"})
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


async def test_export_expenses_no_data(skill, ctx):
    """Empty DB returns 'no expenses' message."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.core.db.async_session",
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg(), ctx, {"export_type": "expenses"})

    assert "No expenses" in result.response_text


async def test_export_expenses_with_data(skill, ctx):
    """Expenses with data returns xlsx document."""
    row = MagicMock()
    row.date = date(2026, 3, 1)
    row.merchant = "Starbucks"
    row.category = "Coffee"
    row.amount = 5.50
    row.description = "Latte"

    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.core.db.async_session",
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg(), ctx, {"export_type": "expenses"})

    assert result.document is not None
    assert result.document_name.endswith(".xlsx")
    assert "1 expenses" in result.response_text or "Exported" in result.response_text


async def test_export_tasks(skill, ctx):
    """Tasks export returns xlsx."""
    row = MagicMock()
    row.title = "Buy milk"
    row.status = "open"
    row.deadline = date(2026, 3, 5)
    row.created_at = "2026-03-01 10:00"
    row.description = ""

    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.core.db.async_session",
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg("export tasks"), ctx, {})

    assert result.document is not None
    assert result.document_name == "tasks.xlsx"


async def test_export_contacts(skill, ctx):
    """Contacts export returns xlsx."""
    row = MagicMock()
    row.name = "John Doe"
    row.phone = "+1555"
    row.email = "john@example.com"
    row.role = "Client"
    row.notes = ""

    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.core.db.async_session",
    ) as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg("export contacts"), ctx, {})

    assert result.document is not None
    assert result.document_name == "contacts.xlsx"
