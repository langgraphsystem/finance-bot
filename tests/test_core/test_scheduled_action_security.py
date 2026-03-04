"""Security tests for scheduled actions isolation and dispatcher filters."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from src.core.context import SessionContext
from src.core.scheduled_actions.callbacks import handle_sched_callback
from src.core.tasks.scheduled_action_tasks import dispatch_scheduled_actions
from src.skills.list_scheduled_actions.handler import get_scheduled_actions
from src.skills.manage_scheduled_action.handler import get_manageable_actions


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):  # noqa: ANN001
        return self._items


class _ExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._items)


class _CaptureSession:
    def __init__(self, items=None, scalar_value=None):
        self.items = items or []
        self.scalar_value = scalar_value
        self.statement = None

    async def execute(self, statement):  # noqa: ANN001
        self.statement = statement
        return _ExecuteResult(self.items)

    async def scalar(self, statement):  # noqa: ANN001
        self.statement = statement
        return self.scalar_value

    async def commit(self) -> None:
        return None


class _SessionCM:
    def __init__(self, session: _CaptureSession):
        self._session = session

    async def __aenter__(self) -> _CaptureSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


def _ctx() -> SessionContext:
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


async def test_list_query_scoped_by_family_and_user():
    family_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session = _CaptureSession(items=[])

    with patch(
        "src.skills.list_scheduled_actions.handler.async_session",
        new=lambda: _SessionCM(session),
    ):
        actions = await get_scheduled_actions(family_id, user_id)

    assert actions == []
    assert session.statement is not None
    sql = str(session.statement).lower()
    assert "scheduled_actions.family_id" in sql
    assert "scheduled_actions.user_id" in sql
    assert "scheduled_actions.status in" in sql


async def test_manage_query_scoped_by_family_and_user():
    family_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session = _CaptureSession(items=[])

    with patch(
        "src.skills.manage_scheduled_action.handler.async_session",
        new=lambda: _SessionCM(session),
    ):
        actions = await get_manageable_actions(family_id, user_id)

    assert actions == []
    assert session.statement is not None
    sql = str(session.statement).lower()
    assert "scheduled_actions.family_id" in sql
    assert "scheduled_actions.user_id" in sql
    assert "scheduled_actions.status in" in sql


async def test_forged_callback_action_id_returns_not_found():
    context = _ctx()
    session = _CaptureSession(scalar_value=None)

    with patch(
        "src.core.scheduled_actions.callbacks.async_session",
        new=lambda: _SessionCM(session),
    ):
        result = await handle_sched_callback(
            sub_action="pause",
            action_id=str(uuid.uuid4()),
            context=context,
        )

    assert "not found" in result.lower()


async def test_dispatch_filters_active_users_and_deleted_actions():
    session = _CaptureSession(items=[])
    now = datetime(2026, 3, 5, 10, 0, tzinfo=UTC)

    with (
        patch("src.core.tasks.scheduled_action_tasks.settings.ff_scheduled_actions", True),
        patch("src.core.tasks.scheduled_action_tasks.now_utc", return_value=now),
        patch(
            "src.core.tasks.scheduled_action_tasks.async_session",
            new=lambda: _SessionCM(session),
        ),
    ):
        await dispatch_scheduled_actions()

    assert session.statement is not None
    sql = str(session.statement).lower()
    assert "join users" in sql
    assert "scheduled_actions.status" in sql
    assert "scheduled_actions.next_run_at" in sql
    assert "users.telegram_id is not null" in sql
    assert "users.onboarded is true" in sql
