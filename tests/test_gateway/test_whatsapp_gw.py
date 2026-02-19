"""Tests for WhatsApp gateway."""

import pytest

from src.gateway.whatsapp_gw import WhatsAppGateway


@pytest.fixture
def gw():
    return WhatsAppGateway(
        api_token="test-token",
        phone_number_id="12345",
        verify_token="my-verify-token",
    )


def test_is_configured(gw):
    assert gw.is_configured


def test_not_configured():
    gw = WhatsAppGateway(api_token="", phone_number_id="")
    assert not gw.is_configured


def test_verify_webhook_success(gw):
    result = gw.verify_webhook("subscribe", "my-verify-token", "challenge123")
    assert result == "challenge123"


def test_verify_webhook_wrong_token(gw):
    result = gw.verify_webhook("subscribe", "wrong-token", "challenge123")
    assert result is None


def test_verify_webhook_wrong_mode(gw):
    result = gw.verify_webhook("unsubscribe", "my-verify-token", "challenge123")
    assert result is None


def test_parse_webhook_text_message(gw):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-1",
                                    "from": "+1234567890",
                                    "type": "text",
                                    "text": {"body": "Hello bot"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = gw.parse_webhook(payload)
    assert msg is not None
    assert msg.text == "Hello bot"
    assert msg.user_id == "+1234567890"
    assert msg.channel == "whatsapp"
    assert msg.channel_user_id == "+1234567890"


def test_parse_webhook_no_messages(gw):
    payload = {"entry": [{"changes": [{"value": {}}]}]}
    assert gw.parse_webhook(payload) is None


def test_parse_webhook_empty(gw):
    assert gw.parse_webhook({}) is None


def test_parse_webhook_image_message(gw):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-2",
                                    "from": "+1234567890",
                                    "type": "image",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = gw.parse_webhook(payload)
    assert msg is not None
    assert "image" in msg.text.lower()


def test_strip_html(gw):
    assert gw._strip_html("<b>bold</b> and <i>italic</i>") == "bold and italic"
    assert gw._strip_html("no tags") == "no tags"
