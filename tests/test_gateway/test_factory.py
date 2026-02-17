"""Tests for gateway factory."""

import os
from unittest.mock import patch

from src.gateway.factory import get_gateway
from src.gateway.telegram import TelegramGateway

# Valid aiogram token format: <bot_id>:<hash>
FAKE_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
def test_get_gateway_telegram():
    """Telegram channel should return TelegramGateway."""
    gw = get_gateway("telegram")
    assert isinstance(gw, TelegramGateway)


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
def test_get_gateway_unknown_falls_back_to_telegram():
    """Unknown channel should fall back to TelegramGateway."""
    gw = get_gateway("unknown_channel")
    assert isinstance(gw, TelegramGateway)


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN})
def test_get_gateway_whatsapp_falls_back():
    """WhatsApp not yet implemented — should fall back to Telegram."""
    gw = get_gateway("whatsapp")
    assert isinstance(gw, TelegramGateway)
