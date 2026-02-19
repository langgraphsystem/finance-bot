"""Slack gateway — converts Slack Events API payloads to IncomingMessage."""

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from src.core.config import settings
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)


class SlackGateway:
    """Gateway for Slack using the Events API and Web API (no slack-bolt dependency)."""

    API_BASE = "https://slack.com/api"

    def __init__(
        self,
        bot_token: str = "",
        signing_secret: str = "",
    ) -> None:
        self._bot_token = bot_token or settings.slack_bot_token
        self._signing_secret = signing_secret or settings.slack_signing_secret
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._bot_token and self._signing_secret)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.API_BASE,
                headers={"Authorization": f"Bearer {self._bot_token}"},
                timeout=10.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Signature verification
    # ------------------------------------------------------------------
    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """Verify Slack request signature (v0)."""
        if abs(time.time() - int(timestamp)) > 300:
            return False
        basestring = f"v0:{timestamp}:{body.decode()}"
        computed = "v0=" + hmac.new(
            self._signing_secret.encode(), basestring.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, signature)

    # ------------------------------------------------------------------
    # Inbound: parse Events API payload
    # ------------------------------------------------------------------
    def parse_event(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse Slack Events API payload into IncomingMessage.

        Returns None for non-message events (url_verification, bot messages, etc.).
        """
        # URL verification challenge
        if payload.get("type") == "url_verification":
            return None

        event = payload.get("event", {})

        # Skip bot messages and message edits
        if event.get("bot_id") or event.get("subtype"):
            return None

        if event.get("type") != "message":
            return None

        return IncomingMessage(
            id=event.get("ts", ""),
            user_id=event.get("user", ""),
            chat_id=event.get("channel", ""),
            type=MessageType.text,
            text=event.get("text", ""),
            channel="slack",
            channel_user_id=event.get("user", ""),
        )

    # ------------------------------------------------------------------
    # Outbound: send messages via Web API
    # ------------------------------------------------------------------
    async def send(self, message: OutgoingMessage) -> None:
        """Send a message to Slack via chat.postMessage."""
        client = await self._get_client()

        blocks = self._build_blocks(message)
        payload: dict[str, Any] = {
            "channel": message.chat_id,
            "text": message.text,  # fallback for notifications
        }
        if blocks:
            payload["blocks"] = blocks

        resp = await client.post("/chat.postMessage", json=payload)
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack send failed: %s", data.get("error", "unknown"))

    async def send_typing(self, chat_id: str) -> None:
        """Slack doesn't have a typing indicator API for bots — no-op."""

    def _build_blocks(self, message: OutgoingMessage) -> list[dict] | None:
        """Convert OutgoingMessage to Slack Block Kit blocks."""
        if not message.buttons:
            return None

        blocks: list[dict] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": message.text}},
        ]

        actions = []
        for btn in message.buttons:
            if "url" in btn:
                actions.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn["text"]},
                    "url": btn["url"],
                })
            elif "callback" in btn:
                actions.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn["text"]},
                    "action_id": btn["callback"],
                    "value": btn["callback"],
                })

        if actions:
            blocks.append({"type": "actions", "elements": actions})

        return blocks

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
