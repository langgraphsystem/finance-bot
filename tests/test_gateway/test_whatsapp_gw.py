"""Tests for WhatsApp gateway."""

from unittest.mock import patch

import pytest

from src.gateway.types import MessageType
from src.gateway.whatsapp_gw import WhatsAppGateway


@pytest.fixture
def gw():
    return WhatsAppGateway(
        api_token="test-token",
        phone_number_id="12345",
        verify_token="my-verify-token",
        app_secret="test-secret",
    )


def test_channel_type(gw):
    assert gw.channel_type == "whatsapp"


def test_is_configured(gw):
    assert gw.is_configured


def test_not_configured():
    with patch("src.gateway.whatsapp_gw.settings") as mock_settings:
        mock_settings.whatsapp_api_token = ""
        mock_settings.whatsapp_phone_number_id = ""
        mock_settings.whatsapp_verify_token = ""
        mock_settings.whatsapp_app_secret = ""
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


def test_verify_signature_valid(gw):
    import hashlib
    import hmac

    body = b'{"test": true}'
    expected = hmac.HMAC(b"test-secret", body, hashlib.sha256).hexdigest()
    assert gw.verify_signature(body, f"sha256={expected}")


def test_verify_signature_invalid(gw):
    assert not gw.verify_signature(b'{"test": true}', "sha256=bad")


def test_verify_signature_no_secret():
    with patch("src.gateway.whatsapp_gw.settings") as mock_settings:
        mock_settings.whatsapp_api_token = ""
        mock_settings.whatsapp_phone_number_id = ""
        mock_settings.whatsapp_verify_token = ""
        mock_settings.whatsapp_app_secret = ""
        gw = WhatsAppGateway(api_token="t", phone_number_id="p", app_secret="")
    assert gw.verify_signature(b"anything", "sha256=anything")


async def test_parse_webhook_text_message(gw):
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
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.text == "Hello bot"
    assert msg.user_id == "+1234567890"
    assert msg.channel == "whatsapp"
    assert msg.channel_user_id == "+1234567890"


async def test_parse_webhook_no_messages(gw):
    payload = {"entry": [{"changes": [{"value": {}}]}]}
    assert await gw.parse_webhook(payload) is None


async def test_parse_webhook_empty(gw):
    assert await gw.parse_webhook({}) is None


async def test_parse_webhook_image_message(gw):
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
                                    "image": {"id": "media-1", "caption": "Check this"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.photo
    assert msg.text == "Check this"


async def test_parse_webhook_document_message(gw):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-3",
                                    "from": "+1234567890",
                                    "type": "document",
                                    "document": {
                                        "id": "media-2",
                                        "filename": "report.pdf",
                                        "mime_type": "application/pdf",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.document
    assert msg.document_file_name == "report.pdf"
    assert msg.document_mime_type == "application/pdf"


async def test_parse_webhook_interactive_button_reply(gw):
    """Button click arrives as interactive message with button_reply."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-btn-1",
                                    "from": "+1234567890",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "onboard:lang:en",
                                            "title": "English",
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.callback
    assert msg.callback_data == "onboard:lang:en"
    assert msg.text == "English"
    assert msg.channel == "whatsapp"
    assert msg.channel_user_id == "+1234567890"


async def test_parse_webhook_interactive_list_reply(gw):
    """List selection arrives as interactive message with list_reply."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-list-1",
                                    "from": "+1234567890",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {
                                            "id": "category:food",
                                            "title": "Food",
                                        },
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.callback
    assert msg.callback_data == "category:food"
    assert msg.text == "Food"


async def test_parse_webhook_location_message(gw):
    """Location message with coordinates and name."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-loc-1",
                                    "from": "+1234567890",
                                    "type": "location",
                                    "location": {
                                        "latitude": 40.7128,
                                        "longitude": -74.0060,
                                        "name": "New York City",
                                        "address": "NY, USA",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.location
    assert "40.7128" in msg.text
    assert "-74.006" in msg.text
    assert "New York City" in msg.text
    assert "NY, USA" in msg.text


async def test_parse_webhook_location_no_name(gw):
    """Location message with only coordinates."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-loc-2",
                                    "from": "+1234567890",
                                    "type": "location",
                                    "location": {
                                        "latitude": 40.7128,
                                        "longitude": -74.0060,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.location
    assert msg.text == "40.7128,-74.006"


async def test_parse_webhook_unsupported_type(gw):
    """Unknown message type falls through to unsupported handler."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "msg-u-1",
                                    "from": "+1234567890",
                                    "type": "contacts",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await gw.parse_webhook(payload)
    assert msg is not None
    assert msg.type == MessageType.text
    assert "contacts" in msg.text
    assert "not supported" in msg.text


def test_strip_html(gw):
    assert gw._strip_html("<b>bold</b> and <i>italic</i>") == "bold and italic"
    assert gw._strip_html("no tags") == "no tags"


def test_edit_message_is_noop(gw):
    """WhatsApp doesn't support editing — method should exist but do nothing."""
    assert hasattr(gw, "edit_message")


def test_delete_message_is_noop(gw):
    """WhatsApp doesn't support deleting — method should exist but do nothing."""
    assert hasattr(gw, "delete_message")
