"""Google OAuth 2.0 endpoints for Gmail + Calendar integration."""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.core.config import settings
from src.core.crypto import encrypt_token
from src.core.db import async_session, redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


@router.get("/google/start")
async def google_oauth_start(state: str = Query(...)):
    """Start the Google OAuth flow. The state token links back to the user."""
    # Verify the state token exists in Redis (set by the bot when user says "connect email")
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    import urllib.parse

    params = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    redirect_url = f"{GOOGLE_AUTH_URL}?{params}"

    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=redirect_url)


@router.get("/google/callback")
async def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle the Google OAuth callback — exchange code for tokens."""
    # Verify state
    user_id = await redis.get(f"oauth_state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    # Exchange code for tokens
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code != 200:
            logger.error("OAuth token exchange failed: %s", resp.text)
            raise HTTPException(status_code=502, detail="Failed to exchange OAuth code.")

        token_data = resp.json()

    # Store encrypted tokens
    from src.core.models.oauth_token import OAuthToken
    from src.core.models.user import User

    async with async_session() as session:
        from sqlalchemy import select

        user = await session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        # Upsert: update existing token or create new one
        existing = await session.scalar(
            select(OAuthToken).where(OAuthToken.user_id == user.id, OAuthToken.provider == "google")
        )

        encrypted_access = encrypt_token(token_data["access_token"])
        encrypted_refresh = encrypt_token(token_data.get("refresh_token", ""))
        expires = datetime.now(UTC) + timedelta(seconds=token_data.get("expires_in", 3600))
        scopes = token_data.get("scope", "").split()

        if existing:
            existing.access_token_encrypted = encrypted_access
            existing.refresh_token_encrypted = encrypted_refresh
            existing.expires_at = expires
            existing.scopes = scopes
        else:
            session.add(
                OAuthToken(
                    user_id=user.id,
                    family_id=user.family_id,
                    provider="google",
                    access_token_encrypted=encrypted_access,
                    refresh_token_encrypted=encrypted_refresh,
                    expires_at=expires,
                    scopes=scopes,
                )
            )
        await session.commit()

    # Clean up state
    await redis.delete(f"oauth_state:{state}")

    return HTMLResponse(
        "<html><body><h2>Connected!</h2>"
        "<p>You can close this window and return to the bot.</p>"
        "</body></html>"
    )


async def generate_oauth_link(user_id: str) -> str:
    """Generate an OAuth deep link for a user. Called by skills when needed."""
    state = secrets.token_urlsafe(32)
    await redis.set(f"oauth_state:{state}", user_id, ex=600)  # 10 min TTL
    # Derive base URL from redirect_uri or webhook_url
    if settings.google_redirect_uri:
        base_url = settings.google_redirect_uri.rsplit("/oauth/", 1)[0]
    elif settings.telegram_webhook_url:
        base_url = settings.telegram_webhook_url.rsplit("/", 1)[0]
    else:
        base_url = "https://localhost:8000"
    return f"{base_url}/oauth/google/start?state={state}"
