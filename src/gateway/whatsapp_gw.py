"""WhatsApp gateway — WhatsApp Business Cloud API via httpx."""

import logging
from typing import Any

import httpx

from src.core.config import settings
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)


class WhatsAppGateway:
    """Gateway for WhatsApp Business Cloud API."""

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        api_token: str = "",
        phone_number_id: str = "",
        verify_token: str = "",
    ) -> None:
        self._api_token = api_token or settings.whatsapp_api_token
        self._phone_id = phone_number_id or settings.whatsapp_phone_number_id
        self._verify_token = verify_token or settings.whatsapp_verify_token
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_token and self._phone_id)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Bearer {self._api_token}"},
                timeout=10.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Webhook verification (GET endpoint)
    # ------------------------------------------------------------------
    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Verify WhatsApp webhook subscription. Returns challenge on success."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    # ------------------------------------------------------------------
    # Inbound: parse webhook payload
    # ------------------------------------------------------------------
    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse WhatsApp Cloud API webhook into IncomingMessage.

        Returns None for status updates, non-text messages, etc.
        """
        entries = payload.get("entry", [])
        if not entries:
            return None

        changes = entries[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        msg_type = msg.get("type", "")
        sender = msg.get("from", "")

        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        else:
            # For now we only handle text messages
            text = f"[{msg_type} message — not supported yet]"

        return IncomingMessage(
            id=msg.get("id", ""),
            user_id=sender,
            chat_id=sender,
            type=MessageType.text,
            text=text,
            channel="whatsapp",
            channel_user_id=sender,
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    async def send(self, message: OutgoingMessage) -> None:
        """Send a text message via WhatsApp Cloud API."""
        client = await self._get_client()

        text = message.text or ""
        # WhatsApp doesn't support HTML — strip tags
        text = self._strip_html(text)

        # Truncate to WhatsApp limit (4096 chars)
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        payload = {
            "messaging_product": "whatsapp",
            "to": message.chat_id,
            "type": "text",
            "text": {"body": text},
        }

        resp = await client.post(f"/{self._phone_id}/messages", json=payload)
        if resp.status_code != 200:
            logger.error("WhatsApp send failed: %s %s", resp.status_code, resp.text[:200])

    async def send_typing(self, chat_id: str) -> None:
        """Slack doesn't have a typing indicator — no-op for WhatsApp too for now."""

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags, keeping inner text."""
        import re

        return re.sub(r"<[^>]+>", "", text)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
