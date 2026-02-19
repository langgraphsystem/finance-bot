"""SMS gateway — Twilio API via httpx (no twilio SDK dependency)."""

import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from src.core.config import settings
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)

# SMS segment limit is 160 chars, but concatenated SMS can be up to ~1600.
SMS_MAX_LENGTH = 1600


class SMSGateway:
    """Gateway for SMS via Twilio REST API (no SDK dependency)."""

    API_BASE = "https://api.twilio.com/2010-04-01"

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        phone_number: str = "",
    ) -> None:
        self._account_sid = account_sid or settings.twilio_account_sid
        self._auth_token = auth_token or settings.twilio_auth_token
        self._phone_number = phone_number or settings.twilio_phone_number
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._phone_number)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.API_BASE,
                auth=(self._account_sid, self._auth_token),
                timeout=10.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Signature verification
    # ------------------------------------------------------------------
    def verify_signature(self, url: str, params: dict, signature: str) -> bool:
        """Verify Twilio request signature."""
        sorted_params = sorted(params.items())
        data = url + "".join(f"{k}{v}" for k, v in sorted_params)
        computed = hmac.new(
            self._auth_token.encode(), data.encode(), hashlib.sha1
        ).digest()
        import base64

        expected = base64.b64encode(computed).decode()
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Inbound: parse Twilio webhook form data
    # ------------------------------------------------------------------
    def parse_webhook(self, form_data: dict[str, Any]) -> IncomingMessage:
        """Parse Twilio SMS webhook form data into IncomingMessage."""
        return IncomingMessage(
            id=form_data.get("MessageSid", ""),
            user_id=form_data.get("From", ""),
            chat_id=form_data.get("From", ""),
            type=MessageType.text,
            text=form_data.get("Body", ""),
            channel="sms",
            channel_user_id=form_data.get("From", ""),
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    async def send(self, message: OutgoingMessage) -> None:
        """Send an SMS via Twilio REST API."""
        client = await self._get_client()

        text = message.text or ""
        # Strip HTML tags — SMS is plain text
        text = self._strip_html(text)

        # Truncate
        if len(text) > SMS_MAX_LENGTH:
            text = text[: SMS_MAX_LENGTH - 20] + "\n... (reply MORE)"

        payload = urlencode({
            "To": message.chat_id,
            "From": self._phone_number,
            "Body": text,
        })

        resp = await client.post(
            f"/Accounts/{self._account_sid}/Messages.json",
            content=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code not in (200, 201):
            logger.error("Twilio send failed: %s %s", resp.status_code, resp.text[:200])

    async def send_typing(self, chat_id: str) -> None:
        """SMS doesn't support typing indicators — no-op."""

    @staticmethod
    def _strip_html(text: str) -> str:
        import re

        return re.sub(r"<[^>]+>", "", text)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
