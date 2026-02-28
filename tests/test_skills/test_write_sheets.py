"""Tests for write_sheets skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.write_sheets.handler import (
    WriteSheetsSkill,
    _extract_spreadsheet_id,
    execute_write_sheets,
)

MODULE = "src.skills.write_sheets.handler"


@pytest.fixture
def skill():
    return WriteSheetsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="write 100 to B2 in https://docs.google.com/spreadsheets/d/abc123xyz/edit",
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

    prompt = SkillResult(response_text="Connect Google", buttons=[{"text": "Connect"}])
    with patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=prompt):
        result = await skill.execute(message, ctx, {})
    assert result.buttons is not None


async def test_no_spreadsheet_id(skill, ctx):
    msg = IncomingMessage(
        id="msg-2", user_id="tg_1", chat_id="chat_1",
        type=MessageType.text, text="write 100 to B2",
    )
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
    ):
        result = await skill.execute(msg, ctx, {})
    assert "link" in result.response_text.lower()


async def test_creates_pending_action(skill, message, ctx):
    """Should create a pending action with confirm/cancel buttons."""
    extracted = '{"range": "Sheet1!B2", "values": [["100"]]}'
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, return_value=extracted),
        patch(
            "src.core.pending_actions.store_pending_action",
            new_callable=AsyncMock, return_value="pending-1",
        ),
    ):
        result = await skill.execute(message, ctx, {})
    assert "Sheet1!B2" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action:pending-1" in result.buttons[0]["callback"]


async def test_extraction_failure(skill, message, ctx):
    with (
        patch(f"{MODULE}.require_google_or_prompt", new_callable=AsyncMock, return_value=None),
        patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=AsyncMock()),
        patch(f"{MODULE}.generate_text", new_callable=AsyncMock, side_effect=ValueError("bad")),
    ):
        result = await skill.execute(message, ctx, {})
    assert "specify" in result.response_text.lower() or "write" in result.response_text.lower()


async def test_execute_write_sheets_success():
    """execute_write_sheets calls google.write_values."""
    mock_google = AsyncMock()
    mock_google.write_values = AsyncMock()
    with patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=mock_google):
        result = await execute_write_sheets(
            {"spreadsheet_id": "abc", "range": "A1", "values": [["x"]]},
            "user-1",
        )
    assert "\u2705" in result
    mock_google.write_values.assert_called_once_with("abc", "A1", [["x"]])


async def test_execute_write_sheets_no_client():
    action = {"spreadsheet_id": "a", "range": "A1", "values": []}
    with patch(f"{MODULE}.get_google_client", new_callable=AsyncMock, return_value=None):
        result = await execute_write_sheets(action, "u")
    assert "connect" in result.lower() or "error" in result.lower()


def test_extract_spreadsheet_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMd/edit"
    assert _extract_spreadsheet_id(url) == "1BxiMVs0XRA5nFMd"


def test_extract_spreadsheet_id_none():
    assert _extract_spreadsheet_id("just text") is None
