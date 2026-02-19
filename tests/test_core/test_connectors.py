"""Tests for ConnectorRegistry."""

from src.core.connectors import ConnectorRegistry


class FakeConnector:
    """Minimal connector for testing."""

    def __init__(self, name: str, configured: bool = True, connected: bool = False):
        self.name = name
        self.is_configured = configured
        self._connected = connected

    async def connect(self, user_id: str) -> str:
        return f"https://auth.example.com/{self.name}"

    async def disconnect(self, user_id: str) -> bool:
        self._connected = False
        return True

    async def is_connected(self, user_id: str) -> bool:
        return self._connected

    async def get_client(self, user_id: str):
        return {"client": self.name}

    async def refresh_if_needed(self, user_id: str) -> None:
        pass


def test_register_and_get():
    registry = ConnectorRegistry()
    conn = FakeConnector("google")
    registry.register(conn)
    assert registry.get("google") is conn


def test_get_returns_none_for_unknown():
    registry = ConnectorRegistry()
    assert registry.get("nonexistent") is None


def test_list_configured():
    registry = ConnectorRegistry()
    registry.register(FakeConnector("google", configured=True))
    registry.register(FakeConnector("slack", configured=False))
    registry.register(FakeConnector("stripe", configured=True))
    assert sorted(registry.list_configured()) == ["google", "stripe"]


async def test_list_connected():
    registry = ConnectorRegistry()
    registry.register(FakeConnector("google", connected=True))
    registry.register(FakeConnector("slack", connected=False))
    result = await registry.list_connected("user-1")
    assert result == ["google"]


async def test_connect_returns_url():
    conn = FakeConnector("google")
    url = await conn.connect("user-1")
    assert "google" in url


async def test_disconnect():
    conn = FakeConnector("google", connected=True)
    assert await conn.is_connected("user-1")
    await conn.disconnect("user-1")
    assert not await conn.is_connected("user-1")
