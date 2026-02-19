"""Tests for Slack gateway."""

import pytest

from src.gateway.slack_gw import SlackGateway


@pytest.fixture
def gw():
    return SlackGateway(bot_token="xoxb-test", signing_secret="test-secret")


def test_is_configured(gw):
    assert gw.is_configured


def test_not_configured():
    gw = SlackGateway(bot_token="", signing_secret="")
    assert not gw.is_configured


def test_parse_event_message(gw):
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C456",
            "ts": "1234567890.123456",
            "text": "hello bot",
        },
    }
    msg = gw.parse_event(payload)
    assert msg is not None
    assert msg.text == "hello bot"
    assert msg.user_id == "U123"
    assert msg.chat_id == "C456"
    assert msg.channel == "slack"
    assert msg.channel_user_id == "U123"


def test_parse_event_url_verification(gw):
    payload = {"type": "url_verification", "challenge": "abc123"}
    assert gw.parse_event(payload) is None


def test_parse_event_bot_message(gw):
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "bot_id": "B123",
            "channel": "C456",
            "ts": "123",
            "text": "bot reply",
        },
    }
    assert gw.parse_event(payload) is None


def test_parse_event_subtype(gw):
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "subtype": "message_changed",
            "channel": "C456",
            "ts": "123",
        },
    }
    assert gw.parse_event(payload) is None


def test_build_blocks_no_buttons(gw):
    from src.gateway.types import OutgoingMessage

    msg = OutgoingMessage(text="hello", chat_id="C456")
    assert gw._build_blocks(msg) is None


def test_build_blocks_with_buttons(gw):
    from src.gateway.types import OutgoingMessage

    msg = OutgoingMessage(
        text="Choose:",
        chat_id="C456",
        buttons=[
            {"text": "Visit", "url": "https://example.com"},
            {"text": "OK", "callback": "ok_action"},
        ],
    )
    blocks = gw._build_blocks(msg)
    assert len(blocks) == 2
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "actions"
    assert len(blocks[1]["elements"]) == 2
