"""Google connector — wraps existing OAuth flow into BaseConnector protocol.

Delegates to ``src.core.google_auth`` for token management and to
``src.tools.google_workspace.GoogleWorkspaceClient`` for API access.
"""

import logging

from src.core.config import settings

logger = logging.getLogger(__name__)


class GoogleConnector:
    """Google Workspace connector (Gmail + Calendar)."""

    name: str = "google"

    @property
    def is_configured(self) -> bool:
        return bool(settings.google_client_id and settings.google_client_secret)

    async def connect(self, user_id: str) -> str:
        """Return an OAuth authorization URL for the user."""
        from api.oauth import generate_oauth_link

        return await generate_oauth_link(user_id)

    async def disconnect(self, user_id: str) -> bool:
        """Remove stored tokens for the user."""
        import uuid

        from sqlalchemy import delete

        from src.core.db import async_session
        from src.core.models.oauth_token import OAuthToken

        try:
            async with async_session() as session:
                await session.execute(
                    delete(OAuthToken).where(
                        OAuthToken.user_id == uuid.UUID(user_id),
                        OAuthToken.provider == "google",
                    )
                )
                await session.commit()
            return True
        except Exception as e:
            logger.error("Failed to disconnect Google for user %s: %s", user_id, e)
            return False

    async def is_connected(self, user_id: str) -> bool:
        from src.core.google_auth import has_google_connection

        return await has_google_connection(user_id)

    async def get_client(self, user_id: str):
        """Return a ready-to-use ``GoogleWorkspaceClient`` (auto-refreshes tokens)."""
        from src.core.google_auth import get_google_client

        return await get_google_client(user_id)

    async def refresh_if_needed(self, user_id: str) -> None:
        """Refresh is handled transparently inside ``get_client``."""


google_connector = GoogleConnector()
