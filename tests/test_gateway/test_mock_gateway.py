"""Tests for MockGateway."""

import pytest

from src.gateway.mock import MockGateway
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage


@pytest.mark.asyncio
async def test_mock_gateway_send():
    gw = MockGateway()
    msg = OutgoingMessage(text="Hello", chat_id="123")
    await gw.send(msg)
    assert len(gw.sent_messages) == 1
    assert gw.last_message.text == "Hello"


@pytest.mark.asyncio
async def test_mock_gateway_send_typing():
    gw = MockGateway()
    await gw.send_typing("123")  # should not raise


@pytest.mark.asyncio
async def test_mock_gateway_simulate():
    gw = MockGateway()
    received = []

    async def handler(msg):
        received.append(msg)

    gw.on_message(handler)
    await gw.simulate_message(IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="hi"
    ))
    assert len(received) == 1
    assert received[0].text == "hi"


@pytest.mark.asyncio
async def test_mock_gateway_clear():
    gw = MockGateway()
    await gw.send(OutgoingMessage(text="msg1", chat_id="1"))
    await gw.send(OutgoingMessage(text="msg2", chat_id="1"))
    assert len(gw.sent_messages) == 2
    gw.clear()
    assert len(gw.sent_messages) == 0
    assert gw.last_message is None
