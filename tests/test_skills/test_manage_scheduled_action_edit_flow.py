"""F4 acceptance tests for manage_scheduled_action edit flow."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.models.enums import ActionStatus, ScheduleKind
from src.gateway.types import IncomingMessage, MessageType
from src.skills.manage_scheduled_action.handler import ManageScheduledActionSkill


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
        timezone="America/New_York",
    )


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def _action(
    title: str,
    status: ActionStatus = ActionStatus.active,
    schedule_kind: ScheduleKind = ScheduleKind.daily,
    schedule_config: dict | None = None,
    sources: list[str] | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        instruction=title,
        status=status,
        schedule_kind=schedule_kind,
        schedule_config=schedule_config or {"time": "08:00"},
        timezone="America/New_York",
        next_run_at=datetime.now() + timedelta(hours=2),
        created_at=datetime.now(),
        sources=sources or ["calendar", "tasks"],
    )


async def test_edit_flow_move_time_updates_existing_action():
    """F4: "Move my morning brief to 8:30" updates existing action."""
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief")
    original_id = target.id

    with (
        patch("src.skills.manage_scheduled_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.manage_scheduled_action.handler.get_manageable_actions",
            new_callable=AsyncMock,
            return_value=[target],
        ),
        patch(
            "src.skills.manage_scheduled_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            _msg("Move my morning brief to 8:30"),
            _ctx(),
            {
                "manage_operation": "reschedule",
                "managed_action_title": "Morning brief",
                "schedule_time": "08:30",
            },
        )

    assert target.id == original_id
    assert target.schedule_config["time"] == "08:30"
    assert "→" in result.response_text
    mock_save.assert_awaited_once()


async def test_edit_flow_add_source_appends_and_shows_before_after():
    """F4: "Add email to my daily summary" appends source and confirms delta."""
    skill = ManageScheduledActionSkill()
    target = _action("Daily summary", sources=["calendar", "tasks"])

    with (
        patch("src.skills.manage_scheduled_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.manage_scheduled_action.handler.get_manageable_actions",
            new_callable=AsyncMock,
            return_value=[target],
        ),
        patch(
            "src.skills.manage_scheduled_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            _msg("Add email to my daily summary"),
            _ctx(),
            {
                "managed_action_title": "Daily summary",
                "schedule_sources": ["email"],
            },
        )

    assert "email_highlights" in target.sources
    assert "Updated" in result.response_text
    assert "Before:" in result.response_text
    assert "After:" in result.response_text
    mock_save.assert_awaited_once()


async def test_edit_flow_changes_frequency_and_recomputes_next_run():
    """F4: edit flow applies frequency delta without recreating action."""
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", schedule_kind=ScheduleKind.daily)

    with (
        patch("src.skills.manage_scheduled_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.manage_scheduled_action.handler.get_manageable_actions",
            new_callable=AsyncMock,
            return_value=[target],
        ),
        patch(
            "src.skills.manage_scheduled_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            _msg("Edit my morning brief to weekly at 09:00"),
            _ctx(),
            {
                "managed_action_title": "Morning brief",
                "schedule_frequency": "weekly",
                "schedule_time": "09:00",
            },
        )

    assert target.schedule_kind == ScheduleKind.weekly
    assert target.next_run_at is not None
    assert "Updated" in result.response_text
    mock_save.assert_awaited_once()
