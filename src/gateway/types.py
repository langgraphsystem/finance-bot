from dataclasses import dataclass
from enum import StrEnum


class MessageType(StrEnum):
    text = "text"
    photo = "photo"
    voice = "voice"
    document = "document"
    callback = "callback"
    location = "location"


@dataclass
class IncomingMessage:
    """Universal incoming message — transport-agnostic."""

    id: str
    user_id: str
    chat_id: str
    type: MessageType
    text: str | None = None
    photo_url: str | None = None
    photo_bytes: bytes | None = None
    voice_url: str | None = None
    voice_bytes: bytes | None = None
    document_url: str | None = None
    document_bytes: bytes | None = None
    document_mime_type: str | None = None
    document_file_name: str | None = None
    callback_data: str | None = None
    raw: object = None

    # Multi-channel fields (Phase 1+)
    channel: str = "telegram"
    channel_user_id: str | None = None
    language: str | None = None
    reply_to: str | None = None
    group_id: str | None = None


@dataclass
class OutgoingMessage:
    """Universal outgoing message."""

    text: str
    chat_id: str
    buttons: list[dict] | None = None
    document: bytes | None = None
    document_name: str | None = None
    photo_url: str | None = None
    photo_bytes: bytes | None = None
    chart_url: str | None = None
    parse_mode: str = "HTML"

    # Reply keyboard (e.g., request_location button)
    reply_keyboard: list[dict] | None = None
    remove_reply_keyboard: bool = False

    # Multi-channel fields (Phase 1+)
    channel: str = "telegram"
    requires_approval: bool = False
    approval_action: str | None = None
    approval_data: dict | None = None
