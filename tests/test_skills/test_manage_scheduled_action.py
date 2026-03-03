"""Tests for manage_scheduled_action skill."""

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
    )


async def test_manage_scheduled_action_pause():
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active)

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
            _msg("pause morning brief"),
            _ctx(),
            {"manage_operation": "pause", "managed_action_title": "Morning brief"},
        )

    assert "Paused" in result.response_text
    assert target.status == ActionStatus.paused
    mock_save.assert_awaited_once()


async def test_manage_scheduled_action_resume():
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.paused)

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
            _msg("resume morning brief"),
            _ctx(),
            {"manage_operation": "resume", "managed_action_title": "Morning brief"},
        )

    assert "Resumed" in result.response_text
    assert "Next run:" in result.response_text
    assert target.status == ActionStatus.active
    mock_save.assert_awaited_once()


async def test_manage_scheduled_action_delete():
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active)

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
            _msg("delete morning brief"),
            _ctx(),
            {"manage_operation": "delete", "managed_action_title": "Morning brief"},
        )

    assert "Deleted" in result.response_text
    assert target.status == ActionStatus.deleted
    mock_save.assert_awaited_once()


async def test_manage_scheduled_action_reschedule_needs_time():
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active, ScheduleKind.daily, {"time": "08:00"})

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
            _msg("reschedule morning brief"),
            _ctx(),
            {"manage_operation": "reschedule", "managed_action_title": "Morning brief"},
        )

    assert "What new time should I use?" in result.response_text
    mock_save.assert_not_awaited()
