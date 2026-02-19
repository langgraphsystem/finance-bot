"""Tests for SMS (Twilio) gateway."""

import pytest

from src.gateway.sms_gw import SMSGateway


@pytest.fixture
def gw():
    return SMSGateway(
        account_sid="AC123",
        auth_token="test-token",
        phone_number="+15551234567",
    )


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


def test_strip_html(gw):
    assert gw._strip_html("<b>bold</b>") == "bold"
