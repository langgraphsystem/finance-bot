"""Acceptance tests for scheduled action idempotency and skipped-run behavior."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError

from src.core.models.enums import ActionStatus, OutputMode, RunStatus, ScheduleKind
from src.core.tasks.scheduled_action_tasks import _execute_action


class _NestedTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class _ProfileResult:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Session:
    def __init__(
        self,
        *,
        telegram_id: int | None = 123456,
        profile_row: tuple[int, int] | None = None,
        fail_on_flush: bool = False,
    ):
        self.telegram_id = telegram_id
        self.profile_row = profile_row
        self.fail_on_flush = fail_on_flush
        self.added: list[object] = []

    def begin_nested(self) -> _NestedTx:
        return _NestedTx()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        if self.fail_on_flush:
            raise IntegrityError("duplicate", {}, Exception("duplicate key"))

    async def scalar(self, statement):  # noqa: ANN001
        del statement
        return self.telegram_id

    async def execute(self, statement):  # noqa: ANN001
        del statement
        return _ProfileResult(self.profile_row)


def _action(**kwargs):
    base = {
        "id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "title": "Morning brief",
        "schedule_kind": ScheduleKind.daily,
        "schedule_config": {"time": "08:00"},
        "timezone": "UTC",
        "status": ActionStatus.active,
        "next_run_at": datetime(2026, 3, 6, 8, 0, tzinfo=UTC),
        "run_count": 0,
        "max_runs": None,
        "end_at": None,
        "failure_count": 0,
        "max_failures": 3,
        "last_run_at": None,
        "last_success_at": None,
        "output_mode": OutputMode.compact,
        "language": "en",
        "sources": ["calendar", "tasks"],
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


async def test_execute_action_duplicate_integrity_error_is_caught_and_not_sent():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action()
    session = _Session(fail_on_flush=True)

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
        ) as mock_collect_sources,
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
        patch("src.core.tasks.scheduled_action_tasks.logger.info") as mock_logger_info,
    ):
        await _execute_action(session, action, now)

    mock_collect_sources.assert_not_awaited()
    mock_send_action_message.assert_not_awaited()
    assert any(
        "already exists" in str(call.args[0]).lower()
        for call in mock_logger_info.call_args_list
        if call.args
    )


async def test_execute_action_silent_mode_marks_run_as_skipped():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action()
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="silent",
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
    ):
        await _execute_action(session, action, now)

    mock_send_action_message.assert_not_awaited()
    assert session.added, "Run record should be created before skip decision."
    run = session.added[0]
    assert run.status == RunStatus.skipped
    assert run.error_code == "comm_mode_silent"
