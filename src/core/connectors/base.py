"""Base connector protocol for external service integrations.

Every external service (Google, Slack, Stripe, etc.) implements this
protocol so skills never import API libraries directly — they request
a client from the ConnectorRegistry instead.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseConnector(Protocol):
    """Protocol that all service connectors implement."""

    name: str
    is_configured: bool  # True when required env vars / config are present

    async def connect(self, user_id: str) -> str:
        """Initiate a connection.

        For OAuth services returns the authorization URL.
        For API-key services returns a confirmation string.
        """
        ...

    async def disconnect(self, user_id: str) -> bool:
        """Revoke tokens / remove stored credentials. Returns True on success."""
        ...

    async def is_connected(self, user_id: str) -> bool:
        """Check whether *user_id* has a valid, non-expired connection."""
        ...

    async def get_client(self, user_id: str) -> Any:
        """Return a ready-to-use API client with valid tokens.

        Auto-refreshes tokens if they expire within 5 minutes.
        """
        ...

    async def refresh_if_needed(self, user_id: str) -> None:
        """Refresh credentials if they expire within 5 minutes."""
        ...
