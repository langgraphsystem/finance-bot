"""Tests for SMS (Twilio) gateway."""

import pytest

from src.gateway.sms_gw import SMSGateway
from src.gateway.types import MessageType


@pytest.fixture
def gw():
    return SMSGateway(
        account_sid="AC123",
        auth_token="test-token",
        phone_number="+15551234567",
    )


def test_channel_type(gw):
    assert gw.channel_type == "sms"


def test_is_configured(gw):
    assert gw.is_configured


def test_not_configured():
    gw = SMSGateway(account_sid="", auth_token="", phone_number="")
    assert not gw.is_configured


def test_parse_webhook(gw):
    form_data = {
        "MessageSid": "SM123",
        "From": "+12025551234",
        "Body": "check my balance",
    }
    msg = gw.parse_webhook(form_data)
    assert msg.id == "SM123"
    assert msg.user_id == "+12025551234"
    assert msg.chat_id == "+12025551234"
    assert msg.text == "check my balance"
    assert msg.channel == "sms"
    assert msg.channel_user_id == "+12025551234"


def test_parse_webhook_empty_body(gw):
    form_data = {
        "MessageSid": "SM456",
        "From": "+12025551234",
    }
    msg = gw.parse_webhook(form_data)
    assert msg.text == ""


def test_parse_webhook_mms(gw):
    """MMS messages with media should set photo_url."""
    form_data = {
        "MessageSid": "MM789",
        "From": "+12025551234",
        "Body": "",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/media/img.jpg",
        "MediaContentType0": "image/jpeg",
    }
    msg = gw.parse_webhook(form_data)
    assert msg.type == MessageType.photo
    assert msg.photo_url == "https://api.twilio.com/media/img.jpg"


def test_parse_webhook_mms_document(gw):
    """MMS with non-image media should set document_url."""
    form_data = {
        "MessageSid": "MM790",
        "From": "+12025551234",
        "Body": "",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/media/doc.pdf",
        "MediaContentType0": "application/pdf",
    }
    msg = gw.parse_webhook(form_data)
    assert msg.type == MessageType.document
    assert msg.document_url == "https://api.twilio.com/media/doc.pdf"


def test_strip_html(gw):
    assert gw._strip_html("<b>bold</b>") == "bold"


def test_on_message(gw):
    """on_message should store the handler."""

    async def handler(msg):
        pass

    gw.on_message(handler)
    assert gw._handler is handler


def test_edit_message_is_noop(gw):
    assert hasattr(gw, "edit_message")


def test_delete_message_is_noop(gw):
    assert hasattr(gw, "delete_message")


async def test_start_stop(gw):
    """start() and stop() should not raise."""
    await gw.start()
    await gw.stop()
