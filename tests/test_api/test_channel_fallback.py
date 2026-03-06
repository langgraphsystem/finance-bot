from unittest.mock import AsyncMock, patch

import pytest

from src.gateway.types import IncomingMessage, MessageType


@pytest.mark.asyncio
async def test_handle_channel_message_sends_fallback_on_unhandled_error():
    from api.main import _handle_channel_message

    incoming = IncomingMessage(
        id="1",
        user_id="U123ABC",
        chat_id="C456",
        type=MessageType.text,
        text="hello",
        channel="slack",
        channel_user_id="U123ABC",
    )
    gw = AsyncMock()

    with patch(
        "api.main.build_context_from_channel",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await _handle_channel_message(incoming, gw)

    gw.send.assert_awaited_once()
    sent = gw.send.await_args.args[0]
    assert sent.text == "Произошла ошибка. Попробуйте ещё раз через пару секунд."
    assert sent.chat_id == "C456"
    assert sent.channel == "slack"
