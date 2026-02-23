"""Tests for Slack gateway."""

import hashlib
import hmac
import time

import pytest

from src.gateway.slack_gw import SlackGateway
from src.gateway.types import MessageType, OutgoingMessage


@pytest.fixture
def gw():
    return SlackGateway(bot_token="xoxb-test", signing_secret="test-secret")


def test_channel_type(gw):
    assert gw.channel_type == "slack"


def test_is_configured(gw):
    assert gw.is_configured


def test_not_configured():
    gw = SlackGateway(bot_token="", signing_secret="")
    assert not gw.is_configured


def test_verify_signature_valid(gw):
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    basestring = f"v0:{ts}:{body.decode()}"
    expected = "v0=" + hmac.HMAC(
        b"test-secret", basestring.encode(), hashlib.sha256
    ).hexdigest()
    assert gw.verify_signature(body, ts, expected)


def test_verify_signature_invalid(gw):
    ts = str(int(time.time()))
    assert not gw.verify_signature(b"body", ts, "v0=bad")


def test_verify_signature_old_timestamp(gw):
    ts = str(int(time.time()) - 600)  # 10 minutes ago
    assert not gw.verify_signature(b"body", ts, "v0=anything")


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


def test_parse_event_with_file(gw):
    """File attachments should be parsed."""
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C456",
            "ts": "123",
            "text": "here's a file",
            "files": [
                {
                    "id": "F123",
                    "name": "report.pdf",
                    "mimetype": "application/pdf",
                    "url_private_download": "https://files.slack.com/files/report.pdf",
                }
            ],
        },
    }
    msg = gw.parse_event(payload)
    assert msg is not None
    assert msg.type == MessageType.document
    assert msg.document_file_name == "report.pdf"


def test_parse_event_with_image_file(gw):
    """Image file attachments should be parsed as photos."""
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "user": "U123",
            "channel": "C456",
            "ts": "123",
            "text": "",
            "files": [
                {
                    "id": "F456",
                    "name": "screenshot.png",
                    "mimetype": "image/png",
                    "url_private_download": "https://files.slack.com/files/screenshot.png",
                }
            ],
        },
    }
    msg = gw.parse_event(payload)
    assert msg is not None
    assert msg.type == MessageType.photo


def test_build_blocks_no_buttons(gw):
    msg = OutgoingMessage(text="hello", chat_id="C456")
    assert gw._build_blocks(msg) is None


def test_build_blocks_with_buttons(gw):
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


def test_on_message(gw):
    """on_message should store the handler."""

    async def handler(msg):
        pass

    gw.on_message(handler)
    assert gw._handler is handler


async def test_start_stop(gw):
    """start() and stop() should not raise."""
    await gw.start()
    await gw.stop()
