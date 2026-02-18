"""Tests for reminder dispatch cron task."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "src.core.tasks.reminder_tasks"


@pytest.mark.asyncio
async def test_dispatch_sends_due_reminders():
    """Due reminders are sent via Telegram and marked done."""
    task_id = uuid.uuid4()
    telegram_id = 123456

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.title = "Pick up Emma"
    mock_task.description = None

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_task, telegram_id)]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session", return_value=mock_session),
        patch(f"{MODULE}._send_telegram_message", new_callable=AsyncMock) as mock_send,
    ):
        from src.core.tasks.reminder_tasks import dispatch_due_reminders

        await dispatch_due_reminders()

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == telegram_id
    assert "Pick up Emma" in call_args[0][1]
    assert "Напоминание" in call_args[0][1]
    # Should commit (mark as done)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_no_due_reminders():
    """No action when no reminders are due."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session", return_value=mock_session),
        patch(f"{MODULE}._send_telegram_message", new_callable=AsyncMock) as mock_send,
    ):
        from src.core.tasks.reminder_tasks import dispatch_due_reminders

        await dispatch_due_reminders()

    mock_send.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_includes_description():
    """Reminder with description includes it in the message."""
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.title = "Call dentist"
    mock_task.description = "Dr. Smith at 555-0123"

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_task, 999)]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{MODULE}.async_session", return_value=mock_session),
        patch(f"{MODULE}._send_telegram_message", new_callable=AsyncMock) as mock_send,
    ):
        from src.core.tasks.reminder_tasks import dispatch_due_reminders

        await dispatch_due_reminders()

    text = mock_send.call_args[0][1]
    assert "Call dentist" in text
    assert "Dr. Smith" in text
