"""Tests for scheduled action callbacks."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.core.context import SessionContext
from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.scheduled_actions.callbacks import handle_sched_callback


def _context() -> SessionContext:
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


def _action(ctx: SessionContext, **kwargs):
    base = {
        "id": uuid.uuid4(),
        "family_id": uuid.UUID(ctx.family_id),
        "user_id": uuid.UUID(ctx.user_id),
        "title": "Morning brief",
        "schedule_kind": ScheduleKind.daily,
        "schedule_config": {"time": "08:00", "snooze_minutes": 15},
        "timezone": "UTC",
        "status": ActionStatus.active,
        "next_run_at": datetime(2026, 3, 4, 8, 0, tzinfo=UTC),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class _Session:
    def __init__(self, action):
        self.action = action
        self.committed = False

    async def scalar(self, _stmt):  # noqa: ANN001
        return self.action

    async def commit(self) -> None:
        self.committed = True


class _SessionCM:
    def __init__(self, session: _Session):
        self._session = session

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


async def test_sched_callback_invalid_id():
    ctx = _context()

    result = await handle_sched_callback(sub_action="pause", action_id="bad-id", context=ctx)

    assert "Invalid" in result


async def test_sched_callback_pause_updates_status():
    ctx = _context()
    action = _action(ctx, status=ActionStatus.active)
    session = _Session(action)

    with patch(
        "src.core.scheduled_actions.callbacks.async_session",
        new=lambda: _SessionCM(session),
    ):
        result = await handle_sched_callback(
            sub_action="pause",
            action_id=str(action.id),
            context=ctx,
        )

    assert action.status == ActionStatus.paused
    assert session.committed is True
    assert "Paused" in result


async def test_sched_callback_snooze_shifts_next_run():
    ctx = _context()
    action = _action(ctx)
    session = _Session(action)
    now = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    with (
        patch(
            "src.core.scheduled_actions.callbacks.async_session",
            new=lambda: _SessionCM(session),
        ),
        patch("src.core.scheduled_actions.callbacks.now_utc", return_value=now),
    ):
        result = await handle_sched_callback(
            sub_action="snooze",
            action_id=str(action.id),
            context=ctx,
        )

    assert action.next_run_at == datetime(2026, 3, 4, 10, 15, tzinfo=UTC)
    assert "15 min" in result


async def test_sched_callback_delete_marks_deleted():
    ctx = _context()
    action = _action(ctx, status=ActionStatus.active)
    session = _Session(action)

    with patch(
        "src.core.scheduled_actions.callbacks.async_session",
        new=lambda: _SessionCM(session),
    ):
        result = await handle_sched_callback(
            sub_action="del",
            action_id=str(action.id),
            context=ctx,
        )

    assert action.status == ActionStatus.deleted
    assert action.next_run_at is None
    assert "Deleted" in result
