"""Tests for morning_brief skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.morning_brief.handler import MorningBriefSkill

MODULE = "src.skills.morning_brief.handler"


@pytest.fixture
def skill():
    return MorningBriefSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="give me my morning brief",
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


@pytest.mark.asyncio
async def test_morning_brief_no_data(skill, message, ctx):
    """Returns fallback when all collectors return empty."""
    mock_sess = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar.return_value = None
    mock_sess.execute = AsyncMock(return_value=mock_result)

    mock_google = AsyncMock()
    mock_google.is_connected = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session") as mock_session,
        patch(f"{MODULE}.connector_registry") as mock_reg,
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get.return_value = mock_google

        result = await skill.execute(message, ctx, {})

    assert result.response_text


@pytest.mark.asyncio
async def test_morning_brief_with_tasks(skill, message, ctx):
    """Generates brief when task data is available."""
    mock_task = MagicMock()
    mock_task.title = "Buy groceries"
    mock_task.priority = MagicMock(value="high")
    mock_task.due_at = None

    mock_sess = AsyncMock()
    mock_result_tasks = MagicMock()
    mock_result_tasks.scalars.return_value.all.return_value = [mock_task]
    mock_result_empty = MagicMock()
    mock_result_empty.scalars.return_value.all.return_value = []
    mock_result_empty.scalar.return_value = None

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_result_tasks
        return mock_result_empty

    mock_sess.execute = mock_execute
    mock_google = AsyncMock()
    mock_google.is_connected = AsyncMock(return_value=False)

    mock_gen = AsyncMock(return_value="<b>Good morning!</b>\nTasks: Buy groceries")

    with (
        patch(f"{MODULE}.async_session") as mock_session,
        patch(f"{MODULE}.connector_registry") as mock_reg,
        patch(f"{MODULE}.generate_text", mock_gen),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get.return_value = mock_google

        result = await skill.execute(message, ctx, {})

    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt


def test_skill_attributes(skill):
    assert skill.name == "morning_brief"
    assert skill.intents == ["morning_brief"]
    assert skill.model == "claude-sonnet-4-6"
