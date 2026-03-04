"""Tests for scheduled action dispatcher execution paths."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.models.enums import ActionStatus, OutputMode, ScheduleKind
from src.core.tasks.scheduled_action_tasks import (
    RUN_RETENTION_DAYS,
    _execute_action,
    cleanup_old_scheduled_action_runs,
)


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
        telegram_id: int | None = 123456,
        profile_row: tuple[int, int] | None = None,
    ):
        self.telegram_id = telegram_id
        self.profile_row = profile_row
        self.added: list[object] = []

    def begin_nested(self) -> _NestedTx:
        return _NestedTx()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

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
        "action_kind": "digest",
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


async def test_execute_action_pre_send_auto_completes_and_notifies():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action(run_count=3, max_runs=3)
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
        ) as mock_collect_sources,
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
    ):
        await _execute_action(session, action, now)

    assert action.status == ActionStatus.completed
    assert action.next_run_at is None
    mock_collect_sources.assert_not_awaited()
    mock_send_action_message.assert_awaited_once()
    assert "Auto-completed" in mock_send_action_message.call_args.args[1]


async def test_execute_action_post_send_auto_completes_on_max_runs_and_notifies():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action(run_count=0, max_runs=1)
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="normal",
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
            return_value=({"calendar": {"items": []}}, {}),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.format_action_message",
            new_callable=AsyncMock,
            return_value=("Digest text", "gpt-5.2", 42, False),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._build_action_buttons",
            return_value=[],
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
    ):
        await _execute_action(session, action, now)

    assert action.status == ActionStatus.completed
    assert action.run_count == 1
    assert action.next_run_at is None
    assert mock_send_action_message.await_count == 2
    assert mock_send_action_message.await_args_list[0].args[1] == "Digest text"
    assert "Auto-completed" in mock_send_action_message.await_args_list[1].args[1]


async def test_execute_action_auto_pauses_after_max_failures_and_notifies():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action(failure_count=2, max_failures=3)
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="normal",
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
            return_value=({"calendar": {"items": []}}, {}),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.format_action_message",
            new_callable=AsyncMock,
            return_value=("Digest text", "gpt-5.2", 42, False),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._build_action_buttons",
            return_value=[],
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Telegram down"),
        ) as mock_send,
    ):
        await _execute_action(session, action, now)

    assert action.status == ActionStatus.paused
    assert action.failure_count == 3
    # 2 calls: failed send attempt + auto-pause notification
    assert mock_send.await_count == 2
    pause_text = mock_send.await_args_list[1].args[1]
    assert "paused" in pause_text.lower() or "паузе" in pause_text.lower()
    assert "3" in pause_text  # failure count


async def test_execute_action_outcome_auto_completes_when_task_done():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action(
        action_kind="outcome",
        schedule_config={"time": "08:00", "completion_condition": "task_completed"},
        sources=["tasks"],
    )
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="normal",
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
            return_value=({"tasks": ""}, {}),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
    ):
        await _execute_action(session, action, now)

    assert action.status == ActionStatus.completed
    assert mock_send_action_message.await_count == 1
    assert "Auto-completed" in mock_send_action_message.await_args.args[1]


async def test_execute_action_sends_budget_card_when_finance_data_has_budget():
    now = datetime(2026, 3, 6, 8, 0, tzinfo=UTC)
    action = _action(sources=["money_summary"])
    session = _Session()

    with (
        patch(
            "src.core.tasks.scheduled_action_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="normal",
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.collect_sources",
            new_callable=AsyncMock,
            return_value=(
                {"money_summary": "This month: $200.00 total\nMonthly budget: $1000.00"},
                {},
            ),
        ),
        patch(
            "src.core.tasks.scheduled_action_tasks.format_action_message",
            new_callable=AsyncMock,
            return_value=("Digest text", None, None, False),
        ),
        patch("src.core.tasks.scheduled_action_tasks._build_action_buttons", return_value=[]),
        patch(
            "src.core.tasks.scheduled_action_tasks.generate_budget_card",
        ) as mock_generate_budget_card,
        patch(
            "src.core.tasks.scheduled_action_tasks._send_action_message",
            new_callable=AsyncMock,
        ) as mock_send_action_message,
    ):
        mock_generate_budget_card.return_value = SimpleNamespace(getvalue=lambda: b"png-bytes")
        await _execute_action(session, action, now)

    mock_generate_budget_card.assert_called_once_with(200.0, 1000.0, language="en")
    assert mock_send_action_message.await_args.kwargs["photo"] == b"png-bytes"


async def test_cleanup_old_runs_deletes_only_completed_actions():
    mock_result = MagicMock()
    mock_result.rowcount = 5

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.core.tasks.scheduled_action_tasks.async_session",
        return_value=mock_session,
    ):
        await cleanup_old_scheduled_action_runs()

    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    # Verify the DELETE statement was called
    stmt = mock_session.execute.call_args.args[0]
    # Compiled SQL should reference scheduled_action_runs
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "scheduled_action_runs" in compiled


def test_run_retention_days_constant():
    assert RUN_RETENTION_DAYS == 90
