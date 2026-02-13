from dataclasses import dataclass, field
from enum import Enum


class MessageType(str, Enum):
    text = "text"
    photo = "photo"
    voice = "voice"
    document = "document"
    callback = "callback"


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
    callback_data: str | None = None
    raw: object = None


@dataclass
class OutgoingMessage:
    """Universal outgoing message."""

    text: str
    chat_id: str
    buttons: list[dict] | None = None
    document: bytes | None = None
    document_name: str | None = None
    photo_url: str | None = None
    chart_url: str | None = None
    parse_mode: str = "HTML"
