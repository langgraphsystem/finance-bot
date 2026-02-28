"""Tests for append_sheets skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.append_sheets.handler import AppendSheetsSkill, _extract_spreadsheet_id

MODULE = "src.skills.append_sheets.handler"


@pytest.fixture
def skill():
    return AppendSheetsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="add row John, 100, paid to https://docs.google.com/spreadsheets/d/abc123xyz/edit",
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


async def test_no_spreadsheet_id(skill, ctx):
    msg = IncomingMessage(
        id="msg-2", user_id="tg_1", chat_id="chat_1",
        type=MessageType.text, text="add row John, 100",
    )
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
    ):
        result = await skill.execute(msg, ctx, {})
    assert "link" in result.response_text.lower()


async def test_appends_rows(skill, message, ctx):
    """Extracts row data and appends to spreadsheet."""
    extracted = '{"range": "Sheet1", "values": [["John", "100", "paid"]]}'
    mock_google = AsyncMock()
    mock_google.append_values = AsyncMock()
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=extracted),
    ):
        result = await skill.execute(message, ctx, {})
    assert "1 row" in result.response_text
    mock_google.append_values.assert_called_once_with(
        "abc123xyz", "Sheet1", [["John", "100", "paid"]]
    )


async def test_appends_multiple_rows(skill, message, ctx):
    extracted = '{"range": "Sheet1", "values": [["A","B"],["C","D"]]}'
    mock_google = AsyncMock()
    mock_google.append_values = AsyncMock()
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=extracted),
    ):
        result = await skill.execute(message, ctx, {})
    assert "2 rows" in result.response_text


async def test_extraction_failure(skill, message, ctx):
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, side_effect=Exception("err")),
    ):
        result = await skill.execute(message, ctx, {})
    assert "specify" in result.response_text.lower() or "row" in result.response_text.lower()


async def test_empty_values(skill, message, ctx):
    extracted = '{"range": "Sheet1", "values": []}'
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=extracted),
    ):
        result = await skill.execute(message, ctx, {})
    assert "determine" in result.response_text.lower() or "data" in result.response_text.lower()


async def test_append_api_failure(skill, message, ctx):
    extracted = '{"range": "Sheet1", "values": [["x"]]}'
    mock_google = AsyncMock()
    mock_google.append_values = AsyncMock(side_effect=Exception("API error"))
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=extracted),
    ):
        result = await skill.execute(message, ctx, {})
    assert "failed" in result.response_text.lower()


def test_extract_spreadsheet_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMd/edit"
    assert _extract_spreadsheet_id(url) == "1BxiMVs0XRA5nFMd"


def test_extract_spreadsheet_id_none():
    assert _extract_spreadsheet_id("hello") is None


def test_system_prompt(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    assert "JSON" in prompt
