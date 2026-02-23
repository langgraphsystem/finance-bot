"""SMS gateway — Twilio API via httpx (no twilio SDK dependency)."""

import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Awaitable, Callable
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
    channel_type: str = "sms"

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
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

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
        computed = hmac.HMAC(self._auth_token.encode(), data.encode(), hashlib.sha1).digest()
        expected = base64.b64encode(computed).decode()
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Inbound: parse Twilio webhook form data
    # ------------------------------------------------------------------
    def parse_webhook(self, form_data: dict[str, Any]) -> IncomingMessage:
        """Parse Twilio SMS/MMS webhook form data into IncomingMessage."""
        sender = form_data.get("From", "")
        text = form_data.get("Body", "")

        # Check for MMS media attachments
        num_media = int(form_data.get("NumMedia", "0"))
        msg_type = MessageType.text
        photo_url: str | None = None
        document_url: str | None = None
        document_mime: str | None = None

        if num_media > 0:
            media_url = form_data.get("MediaUrl0", "")
            content_type = form_data.get("MediaContentType0", "")

            if content_type.startswith("image/"):
                msg_type = MessageType.photo
                photo_url = media_url
            elif media_url:
                msg_type = MessageType.document
                document_url = media_url
                document_mime = content_type

        return IncomingMessage(
            id=form_data.get("MessageSid", ""),
            user_id=sender,
            chat_id=sender,
            type=msg_type,
            text=text,
            photo_url=photo_url,
            document_url=document_url,
            document_mime_type=document_mime,
            channel="sms",
            channel_user_id=sender,
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

        # Convert inline buttons to numbered text options
        if message.buttons:
            options = []
            for i, btn in enumerate(message.buttons, 1):
                label = btn.get("text", "")
                options.append(f"Reply {i} for {label}")
            text += "\n\n" + "\n".join(options)

        # Truncate
        if len(text) > SMS_MAX_LENGTH:
            text = text[: SMS_MAX_LENGTH - 20] + "\n... (reply MORE)"

        payload = urlencode(
            {
                "To": message.chat_id,
                "From": self._phone_number,
                "Body": text,
            }
        )

        resp = await client.post(
            f"/Accounts/{self._account_sid}/Messages.json",
            content=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "Twilio send failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    async def send_document(self, chat_id: str, document: bytes, filename: str) -> None:
        """SMS can't send files — send a text fallback."""
        await self._send_text(chat_id, f"[Document: {filename}]")

    async def send_photo(self, chat_id: str, photo: bytes | str) -> None:
        """Send photo: MMS if URL, text fallback if bytes."""
        if isinstance(photo, str):
            # URL — send as MMS with MediaUrl
            await self._send_mms(chat_id, media_url=photo)
        else:
            await self._send_text(chat_id, "[Image attached — view in app]")

    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        """SMS doesn't support editing — no-op."""

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """SMS doesn't support deleting — no-op."""

    def on_message(
        self,
        handler: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        """Store the incoming message handler callback."""
        self._handler = handler

    async def start(self) -> None:
        """No-op — SMS uses webhook, no long-polling to start."""

    async def stop(self) -> None:
        """Shut down the gateway by closing the HTTP client."""
        await self.close()

    async def send_typing(self, chat_id: str) -> None:
        """SMS doesn't support typing indicators — no-op."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _send_text(self, chat_id: str, text: str) -> None:
        """Send a plain text SMS."""
        client = await self._get_client()
        payload = urlencode(
            {
                "To": chat_id,
                "From": self._phone_number,
                "Body": text,
            }
        )
        resp = await client.post(
            f"/Accounts/{self._account_sid}/Messages.json",
            content=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "Twilio send_text failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    async def _send_mms(self, chat_id: str, media_url: str, body: str = "") -> None:
        """Send an MMS with a media URL."""
        client = await self._get_client()
        params: dict[str, str] = {
            "To": chat_id,
            "From": self._phone_number,
            "MediaUrl": media_url,
        }
        if body:
            params["Body"] = body
        payload = urlencode(params)
        resp = await client.post(
            f"/Accounts/{self._account_sid}/Messages.json",
            content=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "Twilio send_mms failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
