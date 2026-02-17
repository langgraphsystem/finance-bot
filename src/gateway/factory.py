"""Gateway factory — returns the right gateway for a channel type."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.gateway.base import MessageGateway

logger = logging.getLogger(__name__)


def get_gateway(channel: str) -> MessageGateway:
    """Return the gateway implementation for the given channel.

    Phase 1: only Telegram is available.
    Phase 4: WhatsApp, Slack, SMS gateways will be added.
    """
    from src.gateway.telegram import TelegramGateway

    match channel:
        case "telegram":
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            return TelegramGateway(token=token)
        case _:
            logger.warning("Unknown channel %s, falling back to telegram", channel)
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            return TelegramGateway(token=token)
