"""Tests for read_sheets skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.read_sheets.handler import ReadSheetsSkill, _extract_spreadsheet_id

MODULE = "src.skills.read_sheets.handler"


@pytest.fixture
def skill():
    return ReadSheetsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="read https://docs.google.com/spreadsheets/d/abc123xyz/edit",
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
    """Returns connect prompt when Google not connected."""
    from src.skills.base import SkillResult

    prompt = SkillResult(
        response_text="Connect Google",
        buttons=[{"text": "Connect", "url": "https://example.com"}],
    )
    with patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=prompt):
        result = await skill.execute(message, ctx, {})
    assert result.buttons is not None


async def test_connection_error(skill, message, ctx):
    """Returns error when get_google_client fails."""
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=None),
    ):
        result = await skill.execute(message, ctx, {})
    assert "connect" in result.response_text.lower()


async def test_no_id_lists_spreadsheets(skill, ctx):
    """Lists spreadsheets when no URL provided."""
    msg = IncomingMessage(
        id="msg-2", user_id="tg_1", chat_id="chat_1",
        type=MessageType.text, text="show my sheets",
    )
    mock_google = AsyncMock()
    mock_google.list_spreadsheets = AsyncMock(return_value=[
        {"name": "Budget", "id": "sheet1"},
        {"name": "Tracker", "id": "sheet2"},
    ])
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(msg, ctx, {})
    assert "Budget" in result.response_text
    assert "Tracker" in result.response_text


async def test_reads_values_with_url(skill, message, ctx):
    """Reads and formats spreadsheet data when URL provided."""
    mock_google = AsyncMock()
    mock_google.read_values = AsyncMock(return_value=[
        ["Name", "Amount"],
        ["Coffee", "5"],
    ])
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value="Formatted data"),
    ):
        result = await skill.execute(message, ctx, {})
    assert result.response_text == "Formatted data"
    mock_google.read_values.assert_called_once_with("abc123xyz", "Sheet1")


async def test_empty_spreadsheet(skill, message, ctx):
    """Returns empty message when no data."""
    mock_google = AsyncMock()
    mock_google.read_values = AsyncMock(return_value=[])
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
    ):
        result = await skill.execute(message, ctx, {})
    assert "empty" in result.response_text.lower()


async def test_uses_intent_data_range(skill, message, ctx):
    """Uses sheet_range from intent_data."""
    mock_google = AsyncMock()
    mock_google.read_values = AsyncMock(return_value=[["A", "B"]])
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value="ok"),
    ):
        await skill.execute(message, ctx, {"sheet_range": "Sheet2!A1:C10"})
    mock_google.read_values.assert_called_once_with("abc123xyz", "Sheet2!A1:C10")


def test_extract_spreadsheet_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit"
    assert _extract_spreadsheet_id(url) == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"


def test_extract_spreadsheet_id_none():
    assert _extract_spreadsheet_id("hello world") is None


def test_extract_spreadsheet_id_raw():
    assert _extract_spreadsheet_id("read 1BxiMVs0XRA5nFMdKvBdBZjgm") == (
        "1BxiMVs0XRA5nFMdKvBdBZjgm"
    )


def test_system_prompt_includes_language(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
