"""Tests for schedule_action skill."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.models.enums import OutputMode, ScheduleKind
from src.gateway.types import IncomingMessage, MessageType
from src.skills.schedule_action.handler import ScheduleActionSkill


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


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


async def test_schedule_action_daily_creates_action():
    skill = ScheduleActionSkill()
    message = _message("Every day at 8 send me calendar and tasks.")

    with (
        patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.schedule_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "daily",
                "schedule_time": "08:00",
                "schedule_sources": ["calendar", "tasks", "finance"],
                "schedule_instruction": "Send daily digest with calendar and tasks.",
                "schedule_output_mode": "compact",
                "task_title": "Daily plan",
            },
        )

    mock_save.assert_awaited_once()
    action = mock_save.call_args.args[0]
    assert action.schedule_kind == ScheduleKind.daily
    assert action.output_mode == OutputMode.compact
    assert action.sources == ["calendar", "tasks", "money_summary"]
    assert action.next_run_at is not None
    assert action.next_run_at > datetime.now(action.next_run_at.tzinfo)
    assert "<b>Scheduled</b>" in result.response_text
    assert "Sources: calendar, tasks, money" in result.response_text


async def test_schedule_action_once_uses_deadline():
    skill = ScheduleActionSkill()
    message = _message("Schedule once tomorrow.")
    run_at = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat()

    with (
        patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.schedule_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "once",
                "task_deadline": run_at,
                "schedule_instruction": "One-time summary.",
            },
        )

    action = mock_save.call_args.args[0]
    assert action.schedule_kind == ScheduleKind.once
    assert action.schedule_config.get("run_at")
    assert action.schedule_config.get("time")
    assert "once on" in result.response_text


async def test_schedule_action_without_time_asks_for_time():
    skill = ScheduleActionSkill()
    message = _message("Every day send me summary.")

    with patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "daily",
                "schedule_instruction": "Daily summary.",
            },
        )

    assert "What time should I use?" in result.response_text


async def test_schedule_action_disabled_feature_flag():
    skill = ScheduleActionSkill()
    message = _message("Every day at 8 send me summary.")

    with patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", False):
        result = await skill.execute(message, _ctx(), {"schedule_frequency": "daily"})

    assert "not enabled" in result.response_text.lower()


async def test_schedule_action_cron_creates_action():
    skill = ScheduleActionSkill()
    message = _message("Use cron */10 * * * * for summary.")

    with (
        patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.schedule_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "cron",
                "schedule_time": "*/10 * * * *",
                "schedule_instruction": "Cron summary.",
            },
        )

    action = mock_save.call_args.args[0]
    assert action.schedule_kind == ScheduleKind.cron
    assert action.schedule_config["cron_expr"] == "*/10 * * * *"
    assert action.next_run_at is not None
    assert "cron schedule" in result.response_text.lower()


async def test_schedule_action_cron_invalid_asks_for_clarification():
    skill = ScheduleActionSkill()
    message = _message("Use cron every minute.")

    with patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "cron",
                "schedule_time": "* * * * *",
                "schedule_instruction": "Too frequent cron.",
            },
        )

    assert "cron expression" in result.response_text.lower()


async def test_schedule_action_validates_schedule_config():
    skill = ScheduleActionSkill()
    message = _message("Every day at 8 send me summary.")

    with (
        patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True),
        patch(
            "src.skills.schedule_action.handler.ScheduleConfig",
        ) as mock_schedule_config,
        patch(
            "src.skills.schedule_action.handler.save_scheduled_action",
            new_callable=AsyncMock,
        ),
    ):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "daily",
                "schedule_time": "08:00",
                "schedule_instruction": "Daily summary",
                "schedule_sources": ["calendar"],
                "schedule_end_date": "2026-12-31",
                "schedule_max_runs": 10,
            },
        )

    assert "Scheduled" in result.response_text
    assert mock_schedule_config.called
    kwargs = mock_schedule_config.call_args.kwargs
    assert kwargs["time"] == "08:00"
    assert kwargs["max_runs"] == 10
    assert kwargs["end_at"] is not None


async def test_schedule_action_invalid_schedule_config_returns_schedule_prompt():
    skill = ScheduleActionSkill()
    message = _message("Every day at 8 send me summary.")

    with patch("src.skills.schedule_action.handler.settings.ff_scheduled_actions", True):
        result = await skill.execute(
            message,
            _ctx(),
            {
                "schedule_frequency": "daily",
                "schedule_time": "08:00",
                "schedule_instruction": "Daily summary",
                "schedule_sources": ["calendar"],
                "schedule_max_runs": 0,
            },
        )

    assert "When should I run it?" in result.response_text
