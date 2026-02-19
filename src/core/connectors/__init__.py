"""Connector registry — single point of access for all external services.

Usage::

    from src.core.connectors import connector_registry

    google = connector_registry.get("google")
    if google and await google.is_connected(user_id):
        client = await google.get_client(user_id)
        events = await client.list_events(...)
"""

from __future__ import annotations

from src.core.connectors.base import BaseConnector


class ConnectorRegistry:
    """Holds all registered connectors and provides lookup by name."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector instance."""
        self._connectors[connector.name] = connector

    def get(self, name: str) -> BaseConnector | None:
        """Return the connector for *name*, or ``None``."""
        return self._connectors.get(name)

    def list_configured(self) -> list[str]:
        """Return names of connectors whose env vars are present."""
        return [n for n, c in self._connectors.items() if c.is_configured]

    async def list_connected(self, user_id: str) -> list[str]:
        """Return names of connectors where *user_id* has an active connection."""
        connected: list[str] = []
        for name, conn in self._connectors.items():
            if conn.is_configured and await conn.is_connected(user_id):
                connected.append(name)
        return connected


# Module-level singleton — import this from anywhere.
connector_registry = ConnectorRegistry()


def _register_connectors() -> None:
    """Auto-register all known connectors at import time."""
    from src.core.connectors.google import google_connector

    connector_registry.register(google_connector)


_register_connectors()
