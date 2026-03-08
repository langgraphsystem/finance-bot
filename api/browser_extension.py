"""Browser extension API — receive cookies from Chrome extension.

Endpoints:
    POST /api/ext/session   — save cookies for a site
    GET  /api/ext/sessions  — list saved sessions (site names only)
    DELETE /api/ext/session/{site} — delete a saved session
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select

from api.schemas.browser_extension import (
    ExtensionStatusResponse,
    ListSessionsResponse,
    SaveSessionRequest,
    SaveSessionResponse,
    SessionInfo,
)
from src.core.crypto import decrypt_token
from src.core.db import async_session, redis
from src.core.models.browser_session import UserBrowserSession
from src.core.models.user import User
from src.tools import browser_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ext", tags=["browser-extension"])


async def get_user_by_token(authorization: str = Header(...)) -> tuple[str, str]:
    """Validate Bearer token from extension and return (user_id, family_id)."""
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    raw = await redis.get(f"ext_token:{token}")
    if not raw:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = raw if isinstance(raw, str) else raw.decode("utf-8")

    # Look up family_id from users table
    try:
        async with async_session() as session:
            result = await session.execute(
                select(User.family_id).where(User.id == uuid.UUID(user_id))
            )
            row = result.one_or_none()
            if not row:
                raise HTTPException(status_code=401, detail="User not found")
            family_id = str(row[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to look up user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Database error")

    return (user_id, family_id)


@router.post("/session", response_model=SaveSessionResponse)
async def save_session(
    body: SaveSessionRequest,
    user: tuple[str, str] = Depends(get_user_by_token),
):
    """Receive cookies from browser extension and store encrypted."""
    user_id, family_id = user
    domain = browser_service.extract_domain(body.site)

    # Convert extension cookies to Playwright storage_state format
    cookies = [c.model_dump(by_alias=True) for c in body.cookies]
    storage_state = {"cookies": cookies, "origins": []}

    await browser_service.save_storage_state(user_id, family_id, domain, storage_state)
    logger.info(
        "Extension saved %d cookies for user %s on %s",
        len(cookies), user_id, domain,
    )

    return SaveSessionResponse(ok=True, site=domain)


@router.get("/sessions", response_model=ListSessionsResponse)
async def list_sessions(
    user: tuple[str, str] = Depends(get_user_by_token),
):
    """List saved sessions (site names only, no cookie data)."""
    user_id, _ = user

    try:
        async with async_session() as session:
            result = await session.execute(
                select(
                    UserBrowserSession.site,
                    UserBrowserSession.updated_at,
                    UserBrowserSession.storage_state_encrypted,
                ).where(
                    UserBrowserSession.user_id == uuid.UUID(user_id)
                )
            )
            rows = result.all()
    except Exception as e:
        logger.error("Failed to list sessions for %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Database error")

    sessions = []
    for row in rows:
        # Estimate cookie count from encrypted data size (rough)
        cookie_count = 0
        try:
            plaintext = decrypt_token(row.storage_state_encrypted)
            data = json.loads(plaintext)
            cookie_count = len(data.get("cookies", []))
        except Exception:
            pass

        sessions.append(SessionInfo(
            site=row.site,
            cookie_count=cookie_count,
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        ))

    return ListSessionsResponse(sessions=sessions)


@router.get("/status", response_model=ExtensionStatusResponse)
async def extension_status(
    user: tuple[str, str] = Depends(get_user_by_token),
):
    """Validate extension credentials and return connection summary."""
    user_id, family_id = user
    sessions = await browser_service.list_user_sessions(user_id)
    sites = sorted(session["site"] for session in sessions)
    return ExtensionStatusResponse(
        ok=True,
        user_id=user_id,
        family_id=family_id,
        session_count=len(sites),
        sites=sites,
    )


@router.delete("/session/{site}")
async def delete_session(
    site: str,
    user: tuple[str, str] = Depends(get_user_by_token),
):
    """Delete a saved browser session."""
    user_id, _ = user
    deleted = await browser_service.delete_session(user_id, site)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "site": site}
