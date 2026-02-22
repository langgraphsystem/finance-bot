"""Google auth via Composio — connection check and client factory."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.config import settings

if TYPE_CHECKING:
    from src.skills.base import SkillResult
    from src.tools.google_workspace import GoogleWorkspaceClient

logger = logging.getLogger(__name__)


def _composio_client():
    from composio import Composio

    return Composio(api_key=settings.composio_api_key)


async def has_google_connection(user_id: str) -> bool:
    """Check if user has an active Google connection in Composio."""
    try:
        import asyncio

        composio = _composio_client()

        def _check():
            try:
                result = composio.connected_accounts.list(
                    user_ids=[user_id],
                    toolkit_slugs=["GMAIL"],
                    statuses=["ACTIVE"],
                )
                return bool(result.items)
            except Exception:
                return False

        return await asyncio.get_running_loop().run_in_executor(None, _check)
    except Exception as e:
        logger.warning("Failed to check Composio connection: %s", e)
        return False


async def require_google_or_prompt(user_id: str) -> SkillResult | None:
    """Return SkillResult with Composio connect link if not connected, None if connected."""
    from src.skills.base import SkillResult

    if await has_google_connection(user_id):
        return None

    try:
        from api.oauth import generate_composio_connect_link

        link = await generate_composio_connect_link(user_id)
        return SkillResult(
            response_text=(
                "To use email and calendar features, connect your Google account.\n"
                "Click the button below:"
            ),
            buttons=[{"text": "\U0001f517 Connect Google", "url": link}],
        )
    except Exception as e:
        logger.warning("Failed to generate Composio connect link: %s", e)
        return SkillResult(
            response_text="To use email and calendar, connect Google with /connect",
        )


async def get_google_client(user_id: str) -> GoogleWorkspaceClient | None:
    """Return a Composio-backed GoogleWorkspaceClient for the user."""
    from src.tools.google_workspace import GoogleWorkspaceClient

    try:
        if not await has_google_connection(user_id):
            return None
        return GoogleWorkspaceClient(user_id)
    except Exception as e:
        logger.error("Failed to get Google client for user %s: %s", user_id, e)
        return None


def parse_email_headers(msg: dict) -> dict:
    """Extract key fields from a Gmail message metadata response."""
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
    }
