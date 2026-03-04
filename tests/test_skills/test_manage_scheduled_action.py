"""Tests for manage_scheduled_action skill."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.models.enums import ActionStatus, ScheduleKind
from src.gateway.types import IncomingMessage, MessageType
from src.skills.manage_scheduled_action.handler import (
    ManageScheduledActionSkill,
    save_scheduled_action,
)


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
    instruction: str | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        instruction=instruction or title,
        status=status,
        schedule_kind=schedule_kind,
        schedule_config=schedule_config or {"time": "08:00"},
        timezone="America/New_York",
        sources=sources or ["tasks"],
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


async def test_manage_scheduled_action_modify_sources():
    """F4: Test Evolution View when adding sources."""
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active, sources=["tasks"])

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
        ),
    ):
        result = await skill.execute(
            _msg("add calendar to morning brief"),
            _ctx(),
            {
                "manage_operation": "edit",
                "managed_action_title": "Morning brief",
                "added_sources": ["calendar"],
            },
        )

    assert "Action evolved!" in result.response_text
    assert "Sources:" in result.response_text
    assert "calendar" in result.response_text
    assert "calendar" in target.sources


async def test_manage_scheduled_action_modify_instruction():
    """F4: Test Evolution View when updating instruction."""
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active, instruction="Old")

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
        ),
    ):
        result = await skill.execute(
            _msg("change text of morning brief to 'New text'"),
            _ctx(),
            {
                "manage_operation": "edit",
                "managed_action_title": "Morning brief",
                "new_instruction": "New text",
            },
        )

    assert "Action evolved!" in result.response_text
    assert "Instructions: Old → <b>New text</b>" in result.response_text
    assert target.instruction == "New text"


async def test_manage_scheduled_action_modify_alias_maps_to_edit_flow():
    skill = ManageScheduledActionSkill()
    target = _action("Morning brief", ActionStatus.active, sources=["tasks"])

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
        ),
    ):
        result = await skill.execute(
            _msg("add calendar to morning brief"),
            _ctx(),
            {
                "manage_operation": "modify",
                "managed_action_title": "Morning brief",
                "added_sources": ["calendar"],
            },
        )

    assert "Action evolved!" in result.response_text
    assert "calendar" in target.sources


async def test_manage_scheduled_action_edit_time_has_before_after_values():
    skill = ManageScheduledActionSkill()
    target = _action(
        "Morning brief",
        ActionStatus.active,
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "08:00"},
    )

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
        ),
    ):
        result = await skill.execute(
            _msg("move morning brief to 9:30"),
            _ctx(),
            {
                "manage_operation": "edit",
                "managed_action_title": "Morning brief",
                "schedule_time": "09:30",
            },
        )

    assert "Action evolved!" in result.response_text
    assert "08:00" in result.response_text
    assert "<b>09:30</b>" in result.response_text
    assert "..." not in result.response_text


async def test_save_scheduled_action_persists_instruction():
    db_action = _action("Morning brief", instruction="Old text")
    updated = _action("Morning brief", instruction="New text")
    updated.id = db_action.id

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _Session:
        def __init__(self):
            self.committed = False

        async def execute(self, _stmt):  # noqa: ANN001
            return _Result(db_action)

        async def commit(self):
            self.committed = True

    class _SessionCM:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    session = _Session()
    with patch(
        "src.skills.manage_scheduled_action.handler.async_session",
        new=lambda: _SessionCM(session),
    ):
        await save_scheduled_action(updated)

    assert db_action.instruction == "New text"
    assert session.committed is True
