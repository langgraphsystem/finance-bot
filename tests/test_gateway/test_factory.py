"""Tests for gateway factory."""

import os
from unittest.mock import patch

from src.gateway.factory import get_gateway
from src.gateway.slack_gw import SlackGateway
from src.gateway.sms_gw import SMSGateway
from src.gateway.telegram import TelegramGateway
from src.gateway.whatsapp_gw import WhatsAppGateway

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


def test_get_gateway_slack():
    """Slack channel should return SlackGateway."""
    gw = get_gateway("slack")
    assert isinstance(gw, SlackGateway)


def test_get_gateway_whatsapp():
    """WhatsApp channel should return WhatsAppGateway."""
    gw = get_gateway("whatsapp")
    assert isinstance(gw, WhatsAppGateway)


def test_get_gateway_sms():
    """SMS channel should return SMSGateway."""
    gw = get_gateway("sms")
    assert isinstance(gw, SMSGateway)
