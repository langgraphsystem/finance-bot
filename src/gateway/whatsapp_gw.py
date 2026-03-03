"""WhatsApp gateway — WhatsApp Business Cloud API via httpx."""

import hashlib
import hmac
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from src.core.config import settings
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)

# WhatsApp text message limit
WA_TEXT_LIMIT = 4096
# WhatsApp interactive buttons limit
WA_MAX_BUTTONS = 3


class WhatsAppGateway:
    """Gateway for WhatsApp Business Cloud API."""

    BASE_URL = "https://graph.facebook.com/v21.0"
    channel_type: str = "whatsapp"

    def __init__(
        self,
        api_token: str = "",
        phone_number_id: str = "",
        verify_token: str = "",
        app_secret: str = "",
    ) -> None:
        self._api_token = api_token or settings.whatsapp_api_token
        self._phone_id = phone_number_id or settings.whatsapp_phone_number_id
        self._verify_token = verify_token or settings.whatsapp_verify_token
        self._app_secret = app_secret or settings.whatsapp_app_secret
        self._client: httpx.AsyncClient | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_token and self._phone_id)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Bearer {self._api_token}"},
                timeout=30.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Signature verification (X-Hub-Signature-256)
    # ------------------------------------------------------------------
    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify WhatsApp webhook signature using app secret."""
        if not self._app_secret:
            return True  # Skip if no secret configured
        expected = hmac.HMAC(self._app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

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
    async def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse WhatsApp Cloud API webhook into IncomingMessage.

        Handles text, image, document, and audio messages.
        Returns None for status updates or unsupported message types.
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
        msg_id = msg.get("id", "")

        # -- Text message --
        if msg_type == "text":
            return IncomingMessage(
                id=msg_id,
                user_id=sender,
                chat_id=sender,
                type=MessageType.text,
                text=msg.get("text", {}).get("body", ""),
                channel="whatsapp",
                channel_user_id=sender,
                raw=msg,
            )

        # -- Image message --
        if msg_type == "image":
            image_info = msg.get("image", {})
            media_id = image_info.get("id", "")
            caption = image_info.get("caption")
            photo_bytes = await self._download_media(media_id)
            return IncomingMessage(
                id=msg_id,
                user_id=sender,
                chat_id=sender,
                type=MessageType.photo,
                text=caption,
                photo_bytes=photo_bytes,
                channel="whatsapp",
                channel_user_id=sender,
                raw=msg,
            )

        # -- Document message --
        if msg_type == "document":
            doc_info = msg.get("document", {})
            media_id = doc_info.get("id", "")
            caption = doc_info.get("caption")
            doc_bytes = await self._download_media(media_id)
            return IncomingMessage(
                id=msg_id,
                user_id=sender,
                chat_id=sender,
                type=MessageType.document,
                text=caption,
                document_bytes=doc_bytes,
                document_mime_type=doc_info.get("mime_type"),
                document_file_name=doc_info.get("filename"),
                channel="whatsapp",
                channel_user_id=sender,
                raw=msg,
            )

        # -- Audio / voice message --
        if msg_type == "audio":
            audio_info = msg.get("audio", {})
            media_id = audio_info.get("id", "")
            voice_bytes = await self._download_media(media_id)
            return IncomingMessage(
                id=msg_id,
                user_id=sender,
                chat_id=sender,
                type=MessageType.voice,
                voice_bytes=voice_bytes,
                channel="whatsapp",
                channel_user_id=sender,
                raw=msg,
            )

        # -- Interactive message (button clicks / list selections) --
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            itype = interactive.get("type", "")
            if itype == "button_reply":
                reply = interactive.get("button_reply", {})
                return IncomingMessage(
                    id=msg_id,
                    user_id=sender,
                    chat_id=sender,
                    type=MessageType.callback,
                    callback_data=reply.get("id", ""),
                    text=reply.get("title", ""),
                    channel="whatsapp",
                    channel_user_id=sender,
                    raw=msg,
                )
            if itype == "list_reply":
                reply = interactive.get("list_reply", {})
                return IncomingMessage(
                    id=msg_id,
                    user_id=sender,
                    chat_id=sender,
                    type=MessageType.callback,
                    callback_data=reply.get("id", ""),
                    text=reply.get("title", ""),
                    channel="whatsapp",
                    channel_user_id=sender,
                    raw=msg,
                )

        # -- Location message --
        if msg_type == "location":
            loc = msg.get("location", {})
            lat = loc.get("latitude", "")
            lon = loc.get("longitude", "")
            loc_name = loc.get("name", "")
            loc_addr = loc.get("address", "")
            loc_text = f"{lat},{lon}"
            if loc_name:
                loc_text = f"{loc_name}: {loc_text}"
            if loc_addr:
                loc_text = f"{loc_text} ({loc_addr})"
            return IncomingMessage(
                id=msg_id,
                user_id=sender,
                chat_id=sender,
                type=MessageType.location,
                text=loc_text,
                channel="whatsapp",
                channel_user_id=sender,
                raw=msg,
            )

        # -- Unsupported type --
        return IncomingMessage(
            id=msg_id,
            user_id=sender,
            chat_id=sender,
            type=MessageType.text,
            text=f"[{msg_type} message — not supported yet]",
            channel="whatsapp",
            channel_user_id=sender,
            raw=msg,
        )

    # ------------------------------------------------------------------
    # Media download helper
    # ------------------------------------------------------------------
    async def _download_media(self, media_id: str) -> bytes | None:
        """Download media from WhatsApp Cloud API by media ID.

        Step 1: GET /{media_id} to retrieve the download URL.
        Step 2: GET the URL to fetch the actual bytes.
        """
        if not media_id:
            return None
        try:
            client = await self._get_client()
            # Get the media URL
            meta_resp = await client.get(f"/{media_id}")
            if meta_resp.status_code != 200:
                logger.error(
                    "WhatsApp media meta failed: %s %s",
                    meta_resp.status_code,
                    meta_resp.text[:200],
                )
                return None

            media_url = meta_resp.json().get("url")
            if not media_url:
                return None

            # Download actual bytes (absolute URL, needs auth header)
            dl_resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {self._api_token}"},
            )
            if dl_resp.status_code != 200:
                logger.error(
                    "WhatsApp media download failed: %s %s",
                    dl_resp.status_code,
                    dl_resp.text[:200],
                )
                return None

            return dl_resp.content
        except Exception:
            logger.exception("Failed to download WhatsApp media %s", media_id)
            return None

    # ------------------------------------------------------------------
    # Media upload helper
    # ------------------------------------------------------------------
    async def _upload_media(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
    ) -> str | None:
        """Upload media to WhatsApp Cloud API. Returns media_id or None."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/{self._phone_id}/media",
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, data, mime_type)},
            )
            if resp.status_code != 200:
                logger.error(
                    "WhatsApp media upload failed: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            return resp.json().get("id")
        except Exception:
            logger.exception("Failed to upload WhatsApp media")
            return None

    # ------------------------------------------------------------------
    # Outbound: send text / interactive messages
    # ------------------------------------------------------------------
    async def send(self, message: OutgoingMessage) -> None:
        """Send a message via WhatsApp Cloud API.

        Supports plain text and interactive button messages (max 3 buttons).
        Also handles document and photo attachments via OutgoingMessage fields.
        """
        client = await self._get_client()

        # Handle document attachment
        if message.document:
            await self.send_document(
                message.chat_id,
                message.document,
                message.document_name or "file",
            )
            return

        # Handle photo attachment (bytes or URL)
        if message.photo_bytes:
            await self.send_photo(message.chat_id, message.photo_bytes)
            return
        if message.photo_url or message.chart_url:
            url = message.photo_url or message.chart_url or ""
            await self.send_photo(message.chat_id, url)
            return

        text = message.text or ""
        text = self._strip_html(text)
        # Remove surrogates that break JSON serialization
        text = text.encode("utf-8", errors="replace").decode("utf-8")

        # Truncate to WhatsApp limit
        if len(text) > WA_TEXT_LIMIT:
            text = text[: WA_TEXT_LIMIT - 6] + "\n..."

        # Interactive buttons (WhatsApp supports max 3 reply buttons)
        buttons = message.buttons or []
        reply_buttons = [b for b in buttons if "callback" in b][:WA_MAX_BUTTONS]

        if reply_buttons:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": message.chat_id,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text or " "},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": btn["callback"],
                                    "title": btn["text"][:20],
                                },
                            }
                            for btn in reply_buttons
                        ],
                    },
                },
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": message.chat_id,
                "type": "text",
                "text": {"body": text},
            }

        resp = await client.post(f"/{self._phone_id}/messages", json=payload)
        if resp.status_code != 200:
            logger.error(
                "WhatsApp send failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    # ------------------------------------------------------------------
    # Outbound: send document
    # ------------------------------------------------------------------
    async def send_document(self, chat_id: str, document: bytes, filename: str) -> None:
        """Upload and send a document message via WhatsApp Cloud API."""
        # Guess MIME type from filename extension
        mime = _guess_mime(filename)
        media_id = await self._upload_media(document, mime, filename)
        if not media_id:
            logger.error("Cannot send document — media upload failed")
            return

        client = await self._get_client()
        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "document",
            "document": {"id": media_id, "filename": filename},
        }
        resp = await client.post(f"/{self._phone_id}/messages", json=payload)
        if resp.status_code != 200:
            logger.error(
                "WhatsApp send_document failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    # ------------------------------------------------------------------
    # Outbound: send photo
    # ------------------------------------------------------------------
    async def send_photo(self, chat_id: str, photo: bytes | str) -> None:
        """Send an image message via WhatsApp Cloud API.

        If *photo* is a str, it is treated as a public URL (link field).
        If *photo* is bytes, the image is uploaded first.
        """
        client = await self._get_client()

        if isinstance(photo, str):
            # URL-based image
            image_field: dict[str, str] = {"link": photo}
        else:
            # Upload bytes
            media_id = await self._upload_media(photo, "image/png", "image.png")
            if not media_id:
                logger.error("Cannot send photo — media upload failed")
                return
            image_field = {"id": media_id}

        payload = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "image",
            "image": image_field,
        }
        resp = await client.post(f"/{self._phone_id}/messages", json=payload)
        if resp.status_code != 200:
            logger.error(
                "WhatsApp send_photo failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )

    # ------------------------------------------------------------------
    # Typing / read receipts
    # ------------------------------------------------------------------
    async def send_typing(self, chat_id: str) -> None:
        """Mark messages as read (WhatsApp read receipt).

        WhatsApp Cloud API does not have a typing indicator, but marking
        messages as read serves a similar purpose of acknowledging receipt.
        """
        try:
            client = await self._get_client()
            payload = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": chat_id,
            }
            await client.post(f"/{self._phone_id}/messages", json=payload)
        except Exception:
            logger.debug("WhatsApp read receipt failed for %s", chat_id)

    # ------------------------------------------------------------------
    # Edit / delete — not supported by WhatsApp
    # ------------------------------------------------------------------
    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        """No-op — WhatsApp does not support editing sent messages."""

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """No-op — WhatsApp does not support deleting sent messages."""

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------
    def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]) -> None:
        """Store the message handler callback for incoming messages."""
        self._handler = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """No-op — WhatsApp uses webhook-based delivery, no polling."""

    async def stop(self) -> None:
        """Shut down the gateway and release resources."""
        await self.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags, keeping inner text."""
        return re.sub(r"<[^>]+>", "", text)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def _guess_mime(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = filename.rsplit(".", maxsplit=1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "mp4": "video/mp4",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext, "application/octet-stream")
