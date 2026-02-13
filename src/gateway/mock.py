from collections.abc import Awaitable, Callable

from src.gateway.types import IncomingMessage, OutgoingMessage


class MockGateway:
    """Mock gateway for testing — records all sent messages."""

    def __init__(self):
        self.sent_messages: list[OutgoingMessage] = []
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

    async def send(self, message: OutgoingMessage) -> None:
        self.sent_messages.append(message)

    async def send_typing(self, chat_id: str) -> None:
        pass

    def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]) -> None:
        self._handler = handler

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def simulate_message(self, message: IncomingMessage) -> None:
        """Simulate an incoming message for testing."""
        if self._handler:
            await self._handler(message)

    @property
    def last_message(self) -> OutgoingMessage | None:
        return self.sent_messages[-1] if self.sent_messages else None

    def clear(self) -> None:
        self.sent_messages.clear()
