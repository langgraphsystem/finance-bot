"""Tests for list_scheduled_actions skill."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.models.enums import ActionStatus, ScheduleKind
from src.gateway.types import IncomingMessage, MessageType
from src.skills.list_scheduled_actions.handler import ListScheduledActionsSkill


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


def _msg() -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="my scheduled actions",
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
        status=status,
        schedule_kind=schedule_kind,
        schedule_config=schedule_config or {"time": "08:00"},
        timezone="America/New_York",
        next_run_at=datetime.now() + timedelta(hours=2),
        created_at=datetime.now(),
    )


async def test_list_scheduled_actions_with_items():
    skill = ListScheduledActionsSkill()
    actions = [
        _action("Morning brief", ActionStatus.active),
        _action(
            "Weekly summary", ActionStatus.paused,
            ScheduleKind.weekly, {"time": "09:30", "days": [2]},
        ),
    ]

    with (
        patch("src.skills.list_scheduled_actions.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.list_scheduled_actions.handler.get_scheduled_actions",
            new_callable=AsyncMock,
            return_value=actions,
        ),
    ):
        result = await skill.execute(_msg(), _ctx(), {})

    assert "Your scheduled actions" in result.response_text
    assert "▶️ <b>Morning brief</b>" in result.response_text
    assert "⏸" in result.response_text
    assert "Next run:" in result.response_text


async def test_list_scheduled_actions_empty():
    skill = ListScheduledActionsSkill()
    with (
        patch("src.skills.list_scheduled_actions.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.list_scheduled_actions.handler.get_scheduled_actions",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await skill.execute(_msg(), _ctx(), {})

    assert "No scheduled actions yet" in result.response_text


async def test_list_scheduled_actions_disabled():
    skill = ListScheduledActionsSkill()
    with patch("src.skills.list_scheduled_actions.handler.settings.ff_scheduled_actions", False):
        result = await skill.execute(_msg(), _ctx(), {})
    assert "not enabled" in result.response_text.lower()
