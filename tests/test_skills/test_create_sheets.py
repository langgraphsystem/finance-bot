"""Tests for create_sheets skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.create_sheets.handler import CreateSheetsSkill, _extract_title

MODULE = "src.skills.create_sheets.handler"


@pytest.fixture
def skill():
    return CreateSheetsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="create spreadsheet Budget 2026",
    )


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_requires_google(skill, message, ctx):
    from src.skills.base import SkillResult

    prompt = SkillResult(response_text="Connect", buttons=[{"text": "Connect"}])
    with patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=prompt):
        result = await skill.execute(message, ctx, {})
    assert result.buttons is not None


async def test_connection_error(skill, message, ctx):
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=None),
    ):
        result = await skill.execute(message, ctx, {})
    assert "connect" in result.response_text.lower()


async def test_creates_spreadsheet(skill, message, ctx):
    mock_google = AsyncMock()
    mock_google.create_spreadsheet = AsyncMock(return_value={
        "spreadsheetId": "new-id-123",
        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/new-id-123/edit",
    })
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(message, ctx, {})
    assert "Budget 2026" in result.response_text
    assert "new-id-123" in result.response_text
    mock_google.create_spreadsheet.assert_called_once_with("Budget 2026")


async def test_create_failure(skill, message, ctx):
    mock_google = AsyncMock()
    mock_google.create_spreadsheet = AsyncMock(side_effect=Exception("API err"))
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(message, ctx, {})
    assert "failed" in result.response_text.lower()


async def test_fallback_url_from_id(skill, ctx):
    """Builds URL from spreadsheetId when spreadsheetUrl absent."""
    msg = IncomingMessage(
        id="msg-2", user_id="tg_1", chat_id="chat_1",
        type=MessageType.text, text="new sheet Test",
    )
    mock_google = AsyncMock()
    mock_google.create_spreadsheet = AsyncMock(return_value={"spreadsheetId": "xyz"})
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(msg, ctx, {})
    assert "docs.google.com/spreadsheets/d/xyz" in result.response_text


def test_extract_title_english():
    assert _extract_title("create spreadsheet Budget 2026") == "Budget 2026"


def test_extract_title_russian():
    assert _extract_title("создай таблицу Расходы") == "Расходы"


def test_extract_title_spanish():
    assert _extract_title("crear hoja Presupuesto") == "Presupuesto"


def test_extract_title_default():
    assert _extract_title("hi") == "New Spreadsheet"


def test_extract_title_quoted():
    assert _extract_title('create spreadsheet "My Data"') == "My Data"


def test_extract_title_fallback_long_text():
    assert _extract_title("some long text here") == "some long text here"


def test_system_prompt(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    assert "spreadsheet" in prompt.lower()
