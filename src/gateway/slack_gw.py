"""Slack gateway — converts Slack Events API payloads to IncomingMessage."""

import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from src.core.config import settings
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)


class SlackGateway:
    """Gateway for Slack using the Events API and Web API (no slack-bolt dependency)."""

    API_BASE = "https://slack.com/api"
    channel_type: str = "slack"

    def __init__(
        self,
        bot_token: str = "",
        signing_secret: str = "",
    ) -> None:
        self._bot_token = bot_token or settings.slack_bot_token
        self._signing_secret = signing_secret or settings.slack_signing_secret
        self._client: httpx.AsyncClient | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

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
        computed = (
            "v0="
            + hmac.HMAC(
                self._signing_secret.encode(), basestring.encode(), hashlib.sha256
            ).hexdigest()
        )
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

        msg_type = MessageType.text
        document_url: str | None = None
        document_mime: str | None = None
        document_name: str | None = None
        photo_url: str | None = None

        files = event.get("files")
        if files:
            first_file = files[0]
            mimetype = first_file.get("mimetype", "")
            # Use url_private_download if available, fall back to url_private
            file_url = first_file.get(
                "url_private_download",
                first_file.get("url_private", ""),
            )
            if mimetype.startswith("image/"):
                msg_type = MessageType.photo
                photo_url = file_url
            else:
                msg_type = MessageType.document
                document_url = file_url
                document_mime = mimetype
                document_name = first_file.get("name")

        return IncomingMessage(
            id=event.get("ts", ""),
            user_id=event.get("user", ""),
            chat_id=event.get("channel", ""),
            type=msg_type,
            text=event.get("text", ""),
            channel="slack",
            channel_user_id=event.get("user", ""),
            photo_url=photo_url,
            document_url=document_url,
            document_mime_type=document_mime,
            document_file_name=document_name,
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

    async def send_document(
        self,
        chat_id: str,
        document: bytes,
        filename: str,
    ) -> None:
        """Upload a document to Slack using the files.upload v2 flow.

        Steps: getUploadURLExternal → PUT bytes → completeUploadExternal.
        Falls back to a text message if upload fails.
        """
        await self._upload_file(
            chat_id=chat_id,
            file_bytes=document,
            filename=filename,
            fallback_text=f"[Document: {filename}]",
        )

    async def send_photo(
        self,
        chat_id: str,
        photo: bytes | str,
    ) -> None:
        """Send a photo to Slack.

        If *photo* is a ``str`` (URL), post it as a link in a message block.
        If *photo* is ``bytes``, upload via the files.upload v2 flow.
        """
        if isinstance(photo, str):
            client = await self._get_client()
            blocks = [
                {
                    "type": "image",
                    "image_url": photo,
                    "alt_text": "photo",
                },
            ]
            payload: dict[str, Any] = {
                "channel": chat_id,
                "text": photo,
                "blocks": blocks,
            }
            resp = await client.post("/chat.postMessage", json=payload)
            data = resp.json()
            if not data.get("ok"):
                logger.error(
                    "Slack send_photo link failed: %s",
                    data.get("error", "unknown"),
                )
            return

        await self._upload_file(
            chat_id=chat_id,
            file_bytes=photo,
            filename="image.png",
            fallback_text="[Image]",
        )

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        new_text: str,
    ) -> None:
        """Edit a message via chat.update."""
        client = await self._get_client()
        payload = {
            "channel": chat_id,
            "ts": message_id,
            "text": new_text,
        }
        resp = await client.post("/chat.update", json=payload)
        data = resp.json()
        if not data.get("ok"):
            logger.error(
                "Slack edit_message failed: %s",
                data.get("error", "unknown"),
            )

    async def delete_message(
        self,
        chat_id: str,
        message_id: str,
    ) -> None:
        """Delete a message via chat.delete."""
        client = await self._get_client()
        payload = {"channel": chat_id, "ts": message_id}
        resp = await client.post("/chat.delete", json=payload)
        data = resp.json()
        if not data.get("ok"):
            logger.error(
                "Slack delete_message failed: %s",
                data.get("error", "unknown"),
            )

    def on_message(
        self,
        handler: Callable[[IncomingMessage], Awaitable[None]],
    ) -> None:
        """Store the message handler callback.

        Not used directly — events arrive via webhook POST to the API layer.
        """
        self._handler = handler

    async def start(self) -> None:
        """No-op — Slack integration is webhook-based."""

    async def stop(self) -> None:
        """Shut down the gateway (close HTTP client)."""
        await self.close()

    # ------------------------------------------------------------------
    # Internal: Slack files.upload v2 flow
    # ------------------------------------------------------------------
    async def _upload_file(
        self,
        chat_id: str,
        file_bytes: bytes,
        filename: str,
        fallback_text: str,
    ) -> None:
        """Upload a file using the Slack files.upload v2 three-step flow.

        1. ``files.getUploadURLExternal`` — obtain a pre-signed upload URL.
        2. ``PUT`` the raw bytes to that URL.
        3. ``files.completeUploadExternal`` — finalize and share in channel.

        Falls back to posting *fallback_text* if any step fails.
        """
        client = await self._get_client()
        try:
            # Step 1: get upload URL
            step1 = await client.post(
                "/files.getUploadURLExternal",
                json={"filename": filename, "length": len(file_bytes)},
            )
            step1_data = step1.json()
            if not step1_data.get("ok"):
                raise RuntimeError(step1_data.get("error", "unknown"))

            upload_url = step1_data["upload_url"]
            file_id = step1_data["file_id"]

            # Step 2: PUT bytes to the pre-signed URL (no auth header)
            async with httpx.AsyncClient(timeout=30.0) as upload_client:
                put_resp = await upload_client.put(
                    upload_url,
                    content=file_bytes,
                )
                if put_resp.status_code >= 400:
                    raise RuntimeError(f"Upload PUT failed: {put_resp.status_code}")

            # Step 3: complete the upload and share in channel
            step3 = await client.post(
                "/files.completeUploadExternal",
                json={
                    "files": [{"id": file_id, "title": filename}],
                    "channel_id": chat_id,
                },
            )
            step3_data = step3.json()
            if not step3_data.get("ok"):
                raise RuntimeError(step3_data.get("error", "unknown"))

        except Exception:
            logger.exception("Slack file upload failed, sending fallback")
            await self.send(OutgoingMessage(text=fallback_text, chat_id=chat_id))

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
                actions.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": btn["text"]},
                        "url": btn["url"],
                    }
                )
            elif "callback" in btn:
                actions.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": btn["text"]},
                        "action_id": btn["callback"],
                        "value": btn["callback"],
                    }
                )

        if actions:
            blocks.append({"type": "actions", "elements": actions})

        return blocks

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
