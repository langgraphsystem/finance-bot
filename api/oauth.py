"""OAuth endpoints — Composio-managed Google connection for Gmail + Calendar."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core.config import settings
from src.core.db import redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _composio_client():
    from composio import Composio

    return Composio(api_key=settings.composio_api_key)


@router.get("/google/start")
async def google_oauth_start(state: str = Query(...)):
    """Start Google OAuth flow via Composio connection initiation."""
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    if isinstance(user_id, bytes):
        user_id = user_id.decode()

    auth_config_id = settings.composio_gmail_auth_config_id
    if not auth_config_id:
        logger.error("COMPOSIO_GMAIL_AUTH_CONFIG_ID is not set")
        raise HTTPException(status_code=500, detail="Gmail auth config not configured.")

    try:
        composio = _composio_client()

        # Build callback URL for when Composio completes the connection
        if settings.google_redirect_uri:
            base_url = settings.google_redirect_uri.rsplit("/oauth/", 1)[0]
        elif settings.telegram_webhook_url:
            base_url = settings.telegram_webhook_url.rsplit("/", 1)[0]
        else:
            base_url = "https://localhost:8000"
        callback_url = f"{base_url}/oauth/google/callback?state={state}"

        def _initiate():
            return composio.connected_accounts.initiate(
                user_id=user_id,
                auth_config_id=auth_config_id,
                callback_url=callback_url,
            )

        loop = asyncio.get_running_loop()
        connection_request = await loop.run_in_executor(None, _initiate)

        redirect_url = getattr(connection_request, "redirect_url", None) or str(
            connection_request
        )
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error("Composio connection initiation failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to start Google connection.")


@router.get("/google/callback")
async def google_oauth_callback(
    state: str = Query(...),
):
    """Handle the Composio OAuth callback after user authorizes."""
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    # Clean up state
    await redis.delete(f"oauth_state:{state}")

    return HTMLResponse(
        "<html><body><h2>Connected!</h2>"
        "<p>You can close this window and return to the bot.</p>"
        "</body></html>"
    )


async def generate_composio_connect_link(user_id: str) -> str:
    """Generate a Composio connection link for a user. Called by skills."""
    import secrets

    state = secrets.token_urlsafe(32)
    await redis.set(f"oauth_state:{state}", user_id, ex=600)  # 10 min TTL

    if settings.google_redirect_uri:
        base_url = settings.google_redirect_uri.rsplit("/oauth/", 1)[0]
    elif settings.telegram_webhook_url:
        base_url = settings.telegram_webhook_url.rsplit("/", 1)[0]
    else:
        base_url = "https://localhost:8000"
    return f"{base_url}/oauth/google/start?state={state}"


# Keep backward-compat alias
generate_oauth_link = generate_composio_connect_link
