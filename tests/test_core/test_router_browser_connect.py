"""Tests for browser connect resume handling in router slash commands."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType


async def test_start_browser_connect_resumes_taxi_flow(sample_context):
    from src.core.router import _handle_slash_command

    message = IncomingMessage(
        id="1",
        user_id=sample_context.user_id,
        chat_id="chat-1",
        type=MessageType.text,
        text="/start browser_connect",
    )

    with (
        patch(
            "src.tools.taxi_booking.get_taxi_state",
            new_callable=AsyncMock,
            return_value={"step": "awaiting_login"},
        ),
        patch(
            "src.tools.taxi_booking.handle_login_ready",
            new_callable=AsyncMock,
            return_value={"text": "Taxi resumed", "buttons": [{"text": "Confirm"}]},
        ) as mock_resume,
    ):
        result = await _handle_slash_command(message, sample_context)

    assert result is not None
    assert result.text == "Taxi resumed"
    assert result.buttons == [{"text": "Confirm"}]
    mock_resume.assert_awaited_once_with(sample_context.user_id)


async def test_start_browser_connect_resumes_hotel_flow(sample_context):
    from src.core.router import _handle_slash_command

    message = IncomingMessage(
        id="2",
        user_id=sample_context.user_id,
        chat_id="chat-1",
        type=MessageType.text,
        text="/start browser_connect",
    )

    with (
        patch(
            "src.tools.taxi_booking.get_taxi_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value={"step": "awaiting_login"},
        ),
        patch(
            "src.tools.browser_booking.handle_login_ready",
            new_callable=AsyncMock,
            return_value={"text": "Hotel resumed", "buttons": [{"text": "Pick hotel"}]},
        ) as mock_resume,
    ):
        result = await _handle_slash_command(message, sample_context)

    assert result is not None
    assert result.text == "Hotel resumed"
    assert result.buttons == [{"text": "Pick hotel"}]
    mock_resume.assert_awaited_once_with(sample_context.user_id)


async def test_start_browser_connect_without_pending_flow(sample_context):
    from src.core.router import _handle_slash_command

    message = IncomingMessage(
        id="3",
        user_id=sample_context.user_id,
        chat_id="chat-1",
        type=MessageType.text,
        text="/start browser_connect",
    )

    with (
        patch(
            "src.tools.taxi_booking.get_taxi_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.browser_booking.get_booking_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await _handle_slash_command(message, sample_context)

    assert result is not None
    assert "Browser connected" in result.text
