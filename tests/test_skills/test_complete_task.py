"""Tests for complete_task skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import TaskStatus
from src.gateway.types import IncomingMessage, MessageType
from src.skills.complete_task.handler import CompleteTaskSkill


@pytest.fixture
def skill():
    return CompleteTaskSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="done with dentist call",
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


def _mock_completed_task(title="call dentist"):
    task = MagicMock()
    task.title = title
    task.status = TaskStatus.done
    return task


@pytest.mark.asyncio
async def test_complete_task_found(skill, message, ctx):
    """Task is found and marked done."""
    mock_task = _mock_completed_task("call dentist")
    with (
        patch(
            "src.skills.complete_task.handler.find_and_complete_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "src.skills.complete_task.handler.count_open_tasks",
            new_callable=AsyncMock,
            return_value=3,
        ),
    ):
        result = await skill.execute(message, ctx, {"task_title": "dentist call"})

    assert "Marked done: call dentist" in result.response_text
    assert "3 tasks left" in result.response_text


@pytest.mark.asyncio
async def test_complete_task_not_found(skill, message, ctx):
    """No matching task returns helpful message."""
    with patch(
        "src.skills.complete_task.handler.find_and_complete_task",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await skill.execute(message, ctx, {"task_title": "nonexistent task"})

    assert "No open task matching" in result.response_text


@pytest.mark.asyncio
async def test_complete_task_empty_query(skill, ctx):
    """Empty query returns a prompt."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "Which task" in result.response_text


@pytest.mark.asyncio
async def test_complete_task_singular_remaining(skill, message, ctx):
    """Singular 'task' when only 1 remaining."""
    mock_task = _mock_completed_task("buy groceries")
    with (
        patch(
            "src.skills.complete_task.handler.find_and_complete_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "src.skills.complete_task.handler.count_open_tasks",
            new_callable=AsyncMock,
            return_value=1,
        ),
    ):
        result = await skill.execute(message, ctx, {"task_title": "groceries"})

    assert "1 task left" in result.response_text


@pytest.mark.asyncio
async def test_complete_task_zero_remaining(skill, message, ctx):
    """Zero tasks remaining."""
    mock_task = _mock_completed_task("last task")
    with (
        patch(
            "src.skills.complete_task.handler.find_and_complete_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "src.skills.complete_task.handler.count_open_tasks",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        result = await skill.execute(message, ctx, {"task_title": "last task"})

    assert "0 tasks left" in result.response_text
