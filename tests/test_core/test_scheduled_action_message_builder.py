"""Tests for scheduled action message builder and gateway transport."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.models.enums import ActionStatus
from src.core.scheduled_actions.message_builder import build_action_buttons, send_action_message
from src.gateway.types import OutgoingMessage


def _action(status: ActionStatus = ActionStatus.active):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        language="en",
        schedule_config={"snooze_minutes": 15},
    )


def test_build_action_buttons_active_status():
    action = _action(ActionStatus.active)

    buttons = build_action_buttons(action)

    assert [btn["callback"].split(":")[1] for btn in buttons] == ["snooze", "run", "pause"]


def test_build_action_buttons_paused_status():
    action = _action(ActionStatus.paused)

    buttons = build_action_buttons(action)

    assert [btn["callback"].split(":")[1] for btn in buttons] == ["resume", "run"]


async def test_send_action_message_uses_telegram_gateway():
    mock_gateway = MagicMock()
    mock_gateway.send = AsyncMock()
    mock_gateway.bot = SimpleNamespace(
        session=SimpleNamespace(close=AsyncMock()),
    )

    with (
        patch("src.core.scheduled_actions.message_builder.settings.telegram_bot_token", "token"),
        patch(
            "src.core.scheduled_actions.message_builder.get_gateway",
            return_value=mock_gateway,
        ) as mock_get_gateway,
    ):
        await send_action_message(
            telegram_id=123456,
            text="Hello",
            buttons=[{"text": "Run", "callback": "sched:run:abc"}],
        )

    mock_get_gateway.assert_called_once_with("telegram")
    mock_gateway.send.assert_awaited_once()
    payload = mock_gateway.send.await_args.args[0]
    assert isinstance(payload, OutgoingMessage)
    assert payload.chat_id == "123456"
    assert payload.parse_mode == "HTML"
    assert payload.buttons == [{"text": "Run", "callback": "sched:run:abc"}]
    mock_gateway.bot.session.close.assert_awaited_once()
