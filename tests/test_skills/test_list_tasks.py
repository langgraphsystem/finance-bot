"""Tests for list_tasks skill."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import TaskPriority, TaskStatus
from src.gateway.types import IncomingMessage, MessageType
from src.skills.list_tasks.handler import ListTasksSkill


@pytest.fixture
def skill():
    return ListTasksSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="my tasks",
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


def _mock_task(title, priority=TaskPriority.medium, due_at=None):
    task = MagicMock()
    task.title = title
    task.priority = priority
    task.due_at = due_at
    task.status = TaskStatus.pending
    return task


@pytest.mark.asyncio
async def test_list_tasks_with_items(skill, message, ctx):
    """Lists open tasks in priority order."""
    tasks = [
        _mock_task("Buy groceries"),
        _mock_task("Call dentist", priority=TaskPriority.high),
        _mock_task("Fix leak", priority=TaskPriority.urgent),
    ]
    with patch(
        "src.skills.list_tasks.handler.get_open_tasks",
        new_callable=AsyncMock,
        return_value=tasks,
    ):
        result = await skill.execute(message, ctx, {})

    assert "3 open" in result.response_text
    assert "Buy groceries" in result.response_text
    assert "Call dentist" in result.response_text
    assert "Fix leak" in result.response_text


@pytest.mark.asyncio
async def test_list_tasks_empty(skill, message, ctx):
    """Empty task list shows a friendly message."""
    with patch(
        "src.skills.list_tasks.handler.get_open_tasks",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await skill.execute(message, ctx, {})

    assert "No open tasks" in result.response_text


@pytest.mark.asyncio
async def test_list_tasks_with_due_date(skill, message, ctx):
    """Tasks with due dates show the date."""
    due = datetime(2026, 2, 18, 15, 0, tzinfo=UTC)
    tasks = [_mock_task("Pick up Emma", due_at=due)]
    with patch(
        "src.skills.list_tasks.handler.get_open_tasks",
        new_callable=AsyncMock,
        return_value=tasks,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Pick up Emma" in result.response_text
    assert "due" in result.response_text.lower()


@pytest.mark.asyncio
async def test_list_tasks_priority_icons(skill, message, ctx):
    """Priority icons are shown for non-medium tasks."""
    tasks = [
        _mock_task("Urgent thing", priority=TaskPriority.urgent),
        _mock_task("Normal thing", priority=TaskPriority.medium),
    ]
    with patch(
        "src.skills.list_tasks.handler.get_open_tasks",
        new_callable=AsyncMock,
        return_value=tasks,
    ):
        result = await skill.execute(message, ctx, {})

    assert "[urgent]" in result.response_text
    # Medium priority has no icon
    lines = result.response_text.split("\n")
    normal_line = [line for line in lines if "Normal thing" in line][0]
    assert "[medium]" not in normal_line
