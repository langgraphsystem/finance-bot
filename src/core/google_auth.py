"""Google OAuth token management — bridge between DB tokens and GoogleWorkspaceClient."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from aiogoogle.auth.creds import ClientCreds, UserCreds
from sqlalchemy import select

from src.core.config import settings
from src.core.crypto import decrypt_token, encrypt_token
from src.core.db import async_session
from src.core.models.oauth_token import OAuthToken
from src.skills.base import SkillResult
from src.tools.google_workspace import GoogleWorkspaceClient

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


async def has_google_connection(user_id: str) -> bool:
    """Check if user has Google OAuth tokens in DB."""
    try:
        async with async_session() as session:
            result = await session.scalar(
                select(OAuthToken.id)
                .where(OAuthToken.user_id == uuid.UUID(user_id))
                .where(OAuthToken.provider == "google")
                .limit(1)
            )
            return result is not None
    except Exception as e:
        logger.warning("Failed to check Google connection: %s", e)
        return False


async def require_google_or_prompt(user_id: str) -> SkillResult | None:
    """Return SkillResult with OAuth link if not connected, None if connected."""
    if await has_google_connection(user_id):
        return None

    try:
        from api.oauth import generate_oauth_link

        link = await generate_oauth_link(user_id)
        return SkillResult(
            response_text=(
                "Для работы с почтой и календарём нужно подключить Google.\n"
                "Нажмите кнопку ниже:"
            ),
            buttons=[{"text": "🔗 Подключить Google", "url": link}],
        )
    except Exception as e:
        logger.warning("Failed to generate OAuth link: %s", e)
        return SkillResult(
            response_text=(
                "Для работы с почтой и календарём подключите Google "
                "командой /connect"
            ),
        )


async def get_google_client(user_id: str) -> GoogleWorkspaceClient | None:
    """Load OAuth tokens from DB, refresh if expired, return GoogleWorkspaceClient."""
    try:
        async with async_session() as session:
            token = await session.scalar(
                select(OAuthToken)
                .where(OAuthToken.user_id == uuid.UUID(user_id))
                .where(OAuthToken.provider == "google")
                .order_by(OAuthToken.updated_at.desc())
                .limit(1)
            )
            if not token:
                return None

            # Refresh if expiring within 5 minutes
            if token.expires_at < datetime.now(UTC) + timedelta(minutes=5):
                await _refresh_token(token, session)

            access_token = decrypt_token(token.access_token_encrypted)
            refresh_token = decrypt_token(token.refresh_token_encrypted)

            user_creds = UserCreds(
                access_token=access_token,
                refresh_token=refresh_token,
                token_uri=GOOGLE_TOKEN_URL,
                scopes=token.scopes or [],
            )
            client_creds = ClientCreds(
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
            return GoogleWorkspaceClient(user_creds, client_creds)

    except Exception as e:
        logger.error("Failed to get Google client for user %s: %s", user_id, e)
        return None


async def _refresh_token(token: OAuthToken, session) -> None:
    """Refresh an expired Google access token."""
    refresh_token = decrypt_token(token.refresh_token_encrypted)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            logger.error("Token refresh failed: %s", resp.text)
            return

        data = resp.json()
        token.access_token_encrypted = encrypt_token(data["access_token"])
        token.expires_at = datetime.now(UTC) + timedelta(
            seconds=data.get("expires_in", 3600)
        )
        # Google may return a new refresh token
        if data.get("refresh_token"):
            token.refresh_token_encrypted = encrypt_token(data["refresh_token"])

        await session.commit()
        logger.info("Refreshed Google token for user %s", token.user_id)


def parse_email_headers(msg: dict) -> dict:
    """Extract key fields from a Gmail message metadata response."""
    payload = msg.get("payload", {})
    headers = {
        h["name"].lower(): h["value"]
        for h in payload.get("headers", [])
    }
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", "(без темы)"),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
    }
