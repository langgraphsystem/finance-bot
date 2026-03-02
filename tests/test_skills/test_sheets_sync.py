"""Tests for sheets_sync skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.sheets_sync.handler import (
    SheetsSyncSkill,
    _detect_action,
    _detect_scope,
)


@pytest.fixture
def skill():
    return SheetsSyncSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str = "sync to sheets") -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def test_skill_attributes(skill):
    assert skill.name == "sheets_sync"
    assert "sheets_sync" in skill.intents


def test_detect_scope_from_intent():
    assert _detect_scope({"sync_scope": "tasks"}, "") == "tasks"
    assert _detect_scope({"export_type": "contacts"}, "") == "contacts"


def test_detect_scope_from_message():
    assert _detect_scope({}, "sync tasks to sheets") == "tasks"
    assert _detect_scope({}, "синхронизируй контакты") == "contacts"
    assert _detect_scope({}, "sync to sheets") == "expenses"


def test_detect_action():
    assert _detect_action("stop sheets sync") == "stop"
    assert _detect_action("отключи синхронизацию") == "stop"
    assert _detect_action("sheets sync status") == "status"
    assert _detect_action("sync to sheets") == "create"


async def test_requires_google_auth(skill, ctx):
    """Without Google auth, returns auth prompt."""
    with patch(
        "src.skills.sheets_sync.handler.require_google_or_prompt",
        new_callable=AsyncMock,
        return_value="Please connect Google first.",
    ):
        result = await skill.execute(_msg(), ctx, {})
    assert "Google" in result.response_text


async def test_stop_no_syncs(skill, ctx):
    """Stop with no active syncs."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.core.db.async_session") as mock_ctx,
    ):
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg("stop sync"), ctx, {})

    assert "No active syncs" in result.response_text


async def test_status_no_syncs(skill, ctx):
    """Status with no active syncs."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch(
            "src.skills.sheets_sync.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.core.db.async_session") as mock_ctx,
    ):
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await skill.execute(_msg("sheets status"), ctx, {})

    assert "No active syncs" in result.response_text
