"""Gateway factory — returns the right gateway for a channel type."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.gateway.base import MessageGateway

logger = logging.getLogger(__name__)


def get_gateway(channel: str) -> MessageGateway:
    """Return the gateway implementation for the given channel."""
    match channel:
        case "telegram":
            from src.gateway.telegram import TelegramGateway

            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            return TelegramGateway(token=token)
        case "slack":
            from src.gateway.slack_gw import SlackGateway

            return SlackGateway()
        case "whatsapp":
            from src.gateway.whatsapp_gw import WhatsAppGateway

            return WhatsAppGateway()
        case "sms":
            from src.gateway.sms_gw import SMSGateway

            return SMSGateway()
        case _:
            from src.gateway.telegram import TelegramGateway

            logger.warning("Unknown channel %s, falling back to telegram", channel)
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            return TelegramGateway(token=token)
