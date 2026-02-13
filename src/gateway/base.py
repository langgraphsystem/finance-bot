from collections.abc import Awaitable, Callable
from typing import Protocol

from src.gateway.types import IncomingMessage, OutgoingMessage


class MessageGateway(Protocol):
    """Abstract transport interface. Implementations: Telegram, WhatsApp, etc."""

    async def send(self, message: OutgoingMessage) -> None: ...

    async def send_typing(self, chat_id: str) -> None: ...

    def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
