"""Google connector — wraps Composio-managed connection for Gmail + Calendar."""

import logging

from src.core.config import settings

logger = logging.getLogger(__name__)


class GoogleConnector:
    """Google Workspace connector (Gmail + Calendar) via Composio."""

    name: str = "google"

    @property
    def is_configured(self) -> bool:
        return bool(settings.composio_api_key)

    async def connect(self, user_id: str) -> str:
        """Return a Composio OAuth authorization URL for the user."""
        from api.oauth import generate_composio_connect_link

        return await generate_composio_connect_link(user_id)

    async def disconnect(self, user_id: str) -> bool:
        """Disconnect the user's Google account in Composio."""
        try:
            import asyncio

            from src.core.google_auth import _composio_client

            composio = _composio_client()

            def _disconnect():
                result = composio.connected_accounts.list(
                    user_ids=[user_id],
                    toolkit_slugs=["GMAIL"],
                )
                for account in result.items:
                    account_id = getattr(account, "id", None)
                    if account_id:
                        composio.connected_accounts.delete(account_id)
                return True

            return await asyncio.get_running_loop().run_in_executor(None, _disconnect)
        except Exception as e:
            logger.error("Failed to disconnect Google for user %s: %s", user_id, e)
            return False

    async def is_connected(self, user_id: str) -> bool:
        from src.core.google_auth import has_google_connection

        return await has_google_connection(user_id)

    async def get_client(self, user_id: str):
        """Return a ready-to-use ``GoogleWorkspaceClient``."""
        from src.core.google_auth import get_google_client

        return await get_google_client(user_id)

    async def refresh_if_needed(self, user_id: str) -> None:
        """Refresh is handled transparently by Composio."""


google_connector = GoogleConnector()
