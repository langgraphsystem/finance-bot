"""Tests for create_task skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import TaskPriority, TaskStatus
from src.gateway.types import IncomingMessage, MessageType
from src.skills.create_task.handler import CreateTaskSkill


@pytest.fixture
def skill():
    return CreateTaskSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="add task: buy groceries",
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
async def test_create_task_basic(skill, message, ctx):
    """Task is created with title from intent_data."""
    with patch(
        "src.skills.create_task.handler.save_task",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(message, ctx, {"task_title": "buy groceries"})

    mock_save.assert_awaited_once()
    task = mock_save.call_args.args[0]
    assert task.title == "buy groceries"
    assert task.status == TaskStatus.pending
    assert task.priority == TaskPriority.medium
    assert "Added: buy groceries" in result.response_text


@pytest.mark.asyncio
async def test_create_task_high_priority(skill, message, ctx):
    """High-priority keyword is detected."""
    with patch(
        "src.skills.create_task.handler.save_task",
        new_callable=AsyncMock,
    ) as mock_save:
        msg = IncomingMessage(
            id="msg-2",
            user_id="tg_1",
            chat_id="chat_1",
            type=MessageType.text,
            text="urgent task: fix the leak",
        )
        result = await skill.execute(msg, ctx, {"task_title": "fix the leak"})

    task = mock_save.call_args.args[0]
    assert task.priority == TaskPriority.urgent
    assert "urgent" in result.response_text.lower()


@pytest.mark.asyncio
async def test_create_task_with_deadline(skill, message, ctx):
    """Deadline is parsed from intent_data."""
    with patch(
        "src.skills.create_task.handler.save_task",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(
            message,
            ctx,
            {"task_title": "call dentist", "task_deadline": "2026-02-18"},
        )

    task = mock_save.call_args.args[0]
    assert task.due_at is not None
    assert "Due:" in result.response_text


@pytest.mark.asyncio
async def test_create_task_empty_text(skill, ctx):
    """Empty text returns a prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What task" in result.response_text


@pytest.mark.asyncio
async def test_create_task_from_message_text(skill, ctx):
    """Falls back to message.text when intent_data has no task_title."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="pick up Emma from school",
    )
    with patch(
        "src.skills.create_task.handler.save_task",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(msg, ctx, {})

    task = mock_save.call_args.args[0]
    assert task.title == "pick up Emma from school"
    assert "Added:" in result.response_text


@pytest.mark.asyncio
async def test_create_task_priority_from_intent_data(skill, message, ctx):
    """Priority from intent_data takes precedence."""
    with patch(
        "src.skills.create_task.handler.save_task",
        new_callable=AsyncMock,
    ) as mock_save:
        await skill.execute(
            message,
            ctx,
            {"task_title": "review contract", "task_priority": "high"},
        )

    task = mock_save.call_args.args[0]
    assert task.priority == TaskPriority.high
