"""Tests for set_reminder skill — one-shot, recurring, and context extraction."""

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import ReminderRecurrence, TaskPriority, TaskStatus
from src.gateway.types import IncomingMessage, MessageType
from src.skills.set_reminder.handler import (
    SetReminderSkill,
    _parse_recurrence,
    _parse_time_str,
)


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


# ---------------------------------------------------------------------------
# One-shot reminders (existing behavior)
# ---------------------------------------------------------------------------


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
    assert task.recurrence == ReminderRecurrence.none
    assert "3:15 PM" in result.response_text
    assert "pick up Emma" in result.response_text


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
        result = await skill.execute(msg, ctx, {"task_title": "call the dentist"})

    task = mock_save.call_args.args[0]
    assert task.reminder_at is None
    assert "no specific time" in result.response_text.lower()


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


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------


async def test_set_reminder_daily_recurrence(skill, ctx):
    """Daily recurrence stores recurrence=daily and original_reminder_time."""
    msg = IncomingMessage(
        id="msg-5",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me to take vitamins daily at 8am",
    )
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        result = await skill.execute(
            msg,
            ctx,
            {
                "task_title": "take vitamins",
                "task_deadline": "2026-02-20T08:00:00",
                "reminder_recurrence": "daily",
            },
        )

    task = mock_save.call_args.args[0]
    assert task.recurrence == ReminderRecurrence.daily
    assert task.original_reminder_time == "08:00"
    assert task.reminder_at is not None
    # Response should mention recurrence
    assert "daily" in result.response_text.lower() or "ежедневн" in result.response_text.lower()


async def test_set_reminder_weekly_recurrence(skill, ctx):
    """Weekly recurrence stores recurrence=weekly."""
    msg = IncomingMessage(
        id="msg-6",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="weekly reminder to check reports",
    )
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        await skill.execute(
            msg,
            ctx,
            {
                "task_title": "check reports",
                "task_deadline": "2026-02-21T09:00:00",
                "reminder_recurrence": "weekly",
            },
        )

    task = mock_save.call_args.args[0]
    assert task.recurrence == ReminderRecurrence.weekly


async def test_set_reminder_no_recurrence_default(skill, message, ctx):
    """Default recurrence is 'none' for regular reminders."""
    with patch(
        "src.skills.set_reminder.handler.save_reminder",
        new_callable=AsyncMock,
    ) as mock_save:
        await skill.execute(
            message,
            ctx,
            {"task_title": "pick up Emma", "task_deadline": "2026-02-17T15:15:00"},
        )

    task = mock_save.call_args.args[0]
    assert task.recurrence == ReminderRecurrence.none
    assert task.recurrence_end_at is None


# ---------------------------------------------------------------------------
# Context-aware LLM extraction
# ---------------------------------------------------------------------------


@dataclass
class FakeAssembledContext:
    system_prompt: str = "test"
    messages: list = field(default_factory=list)


async def test_context_extraction_multiple_times(skill, ctx):
    """When intent_data has no time but context has times, LLM extracts them."""
    assembled = FakeAssembledContext(
        messages=[
            {
                "role": "assistant",
                "content": "Suhur at 5:08 AM, Iftar at 5:28 PM in Chicago.",
            },
            {"role": "user", "content": "Set daily reminders for these times"},
        ],
    )

    msg = IncomingMessage(
        id="msg-7",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="set daily reminders exactly by time",
    )
    with (
        patch(
            "src.skills.set_reminder.handler.save_reminder",
            new_callable=AsyncMock,
        ) as mock_save,
        patch(
            "src.skills.set_reminder.handler._extract_from_context",
            new_callable=AsyncMock,
            return_value={
                "reminder_title": "Ramadan reminders",
                "reminder_times": [
                    {"time": "05:08", "label": "Suhur"},
                    {"time": "17:28", "label": "Iftar"},
                ],
                "recurrence": "daily",
                "end_date": None,
            },
        ),
    ):
        result = await skill.execute(
            msg,
            ctx,
            {"task_title": "suhur and iftar reminders", "_assembled": assembled},
        )

    # Should create 2 separate reminders
    assert mock_save.await_count == 2
    assert "Suhur" in result.response_text or "5:08" in result.response_text
    assert "Iftar" in result.response_text or "5:28" in result.response_text


async def test_context_extraction_single_time(skill, ctx):
    """Context extraction works for a single time too."""
    assembled = FakeAssembledContext(
        messages=[
            {"role": "assistant", "content": "Your meeting is at 3pm tomorrow."},
            {"role": "user", "content": "Remind me about it"},
        ],
    )

    msg = IncomingMessage(
        id="msg-8",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me about it",
    )
    with (
        patch(
            "src.skills.set_reminder.handler.save_reminder",
            new_callable=AsyncMock,
        ) as mock_save,
        patch(
            "src.skills.set_reminder.handler._extract_from_context",
            new_callable=AsyncMock,
            return_value={
                "reminder_title": "Meeting",
                "reminder_times": [{"time": "15:00", "label": "Meeting"}],
                "recurrence": None,
                "end_date": None,
            },
        ),
    ):
        await skill.execute(
            msg, ctx, {"task_title": "remind me about it", "_assembled": assembled}
        )

    mock_save.assert_awaited_once()
    task = mock_save.call_args.args[0]
    assert task.title == "Meeting"
    assert task.recurrence == ReminderRecurrence.none


async def test_context_extraction_failure_graceful(skill, ctx):
    """When context extraction fails, falls back to no-time behavior."""
    assembled = FakeAssembledContext(
        messages=[{"role": "user", "content": "remind me daily"}],
    )

    msg = IncomingMessage(
        id="msg-9",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="remind me daily",
    )
    with (
        patch(
            "src.skills.set_reminder.handler.save_reminder",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.set_reminder.handler._extract_from_context",
            new_callable=AsyncMock,
            side_effect=Exception("LLM timeout"),
        ),
    ):
        result = await skill.execute(
            msg, ctx, {"task_title": "daily reminder", "_assembled": assembled}
        )

    assert "no specific time" in result.response_text.lower()


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_parse_recurrence_daily():
    assert _parse_recurrence("daily") == ReminderRecurrence.daily


def test_parse_recurrence_weekly():
    assert _parse_recurrence("weekly") == ReminderRecurrence.weekly


def test_parse_recurrence_monthly():
    assert _parse_recurrence("Monthly") == ReminderRecurrence.monthly


def test_parse_recurrence_none():
    assert _parse_recurrence(None) == ReminderRecurrence.none
    assert _parse_recurrence("") == ReminderRecurrence.none
    assert _parse_recurrence("invalid") == ReminderRecurrence.none


def test_parse_time_str_valid():
    dt = _parse_time_str("14:30", "America/New_York")
    assert dt is not None
    assert dt.hour == 14
    assert dt.minute == 30


def test_parse_time_str_invalid():
    assert _parse_time_str("invalid", "America/New_York") is None
    assert _parse_time_str("25:00", "America/New_York") is None
