"""Tests for set_reminder skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import TaskPriority, TaskStatus
from src.gateway.types import IncomingMessage, MessageType
from src.skills.set_reminder.handler import SetReminderSkill


@pytest.fixture
def skill():
    return SetReminderSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me to pick up Emma at 3:15",
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
async def test_set_reminder_with_time(skill, message, ctx):
    """Reminder is created with reminder_at set."""
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(
            message,
            ctx,
            {
                "task_title": "pick up Emma",
                "task_deadline": "2026-02-17T15:15:00",
            },
        )

    mock_save.assert_awaited_once()
    task = mock_save.call_args.args[0]
    assert task.title == "pick up Emma"
    assert task.reminder_at is not None
    assert task.due_at is not None
    assert task.status == TaskStatus.pending
    assert "3:15 PM" in result.response_text
    assert "pick up Emma" in result.response_text


@pytest.mark.asyncio
async def test_set_reminder_without_time(skill, ctx):
    """Reminder without time saves task but notes no time."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me to call the dentist",
    )
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(
            msg, ctx, {"task_title": "call the dentist"}
        )

    task = mock_save.call_args.args[0]
    assert task.reminder_at is None
    assert "no specific time" in result.response_text.lower()


@pytest.mark.asyncio
async def test_set_reminder_empty_text(skill, ctx):
    """Empty text returns a prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "remind you about" in result.response_text.lower()


@pytest.mark.asyncio
async def test_set_reminder_from_message_text(skill, ctx):
    """Falls back to message.text when intent_data has no title."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me to buy milk",
    )
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        await skill.execute(msg, ctx, {})

    task = mock_save.call_args.args[0]
    assert task.title == "remind me to buy milk"
    assert task.priority == TaskPriority.medium
