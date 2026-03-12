from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.request_context import reset_request_context, set_request_context
from src.core.router import _handle_callback, handle_message
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage


def _context() -> SessionContext:
    return SessionContext(
        user_id="user-1",
        family_id="family-1",
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


async def test_feedback_callback_saves_feedback():
    message = IncomingMessage(
        id="cb-1",
        user_id="user-1",
        chat_id="chat-1",
        type=MessageType.callback,
        callback_data="feedback:token-1:helpful",
        channel="telegram",
    )

    with patch("src.core.router.submit_user_feedback", AsyncMock()) as mock_submit:
        result = await _handle_callback(message, _context())

    assert result.text == "Спасибо за оценку."
    mock_submit.assert_awaited_once()


async def test_handle_message_attaches_feedback_buttons_on_success():
    token = set_request_context(request_id="req-1", correlation_id="corr-1")
    message = IncomingMessage(
        id="msg-1",
        user_id="user-1",
        chat_id="chat-1",
        type=MessageType.text,
        text="Привет",
        channel="telegram",
    )
    response = OutgoingMessage(text="Здравствуйте", chat_id="chat-1")

    try:
        with (
            patch("src.core.router.check_rate_limit", AsyncMock(return_value=True)),
            patch("src.core.router._dispatch_message", AsyncMock(return_value=response)),
            patch("src.core.router.create_feedback_buttons", AsyncMock(return_value=[
                {"text": "👍 Помогло", "callback": "feedback:token-1:helpful"},
                {"text": "👎 Не помогло", "callback": "feedback:token-1:unhelpful"},
            ])) as mock_feedback_buttons,
            patch("src.core.router.emit_conversation_analytics_event"),
            patch("src.core.router.log_runtime_event"),
            patch(
                "src.core.memory.user_context.ensure_active_user_session",
                AsyncMock(),
            ),
        ):
            result = await handle_message(message, _context())
    finally:
        reset_request_context(token)

    assert result.buttons is not None
    assert result.buttons[0]["callback"] == "feedback:token-1:helpful"
    mock_feedback_buttons.assert_awaited_once()
