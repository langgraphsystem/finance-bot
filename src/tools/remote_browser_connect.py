"""Hosted browser connect flow for mobile and desktop users.

This module runs a short-lived server-side Playwright session, exposes
screenshots + simple input actions through HTTP, and stores the resulting
authenticated browser storage_state for later automation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

from src.core.config import settings
from src.core.db import redis
from src.tools import browser_service

logger = logging.getLogger(__name__)

CONNECT_TTL_S = 900
VIEWPORT_WIDTH = 430
VIEWPORT_HEIGHT = 932
_TOKEN_PREFIX = "browser_connect"
_AUTH_PATH_HINTS = ("/login", "/signin", "/sign-in", "/auth", "/challenge", "/verify")
_PRESS_KEY_MAP = {
    "enter": "Enter",
    "tab": "Tab",
    "backspace": "Backspace",
    "escape": "Escape",
}
_active_sessions: dict[str, RemoteBrowserSession] = {}
_sessions_lock = asyncio.Lock()


@dataclass
class RemoteBrowserSession:
    token: str
    user_id: str
    family_id: str
    provider: str
    playwright: Any
    browser: Any
    context: Any
    page: Any
    created_at: float
    updated_at: float
    screenshot_png: bytes = b""
    current_url: str = ""
    status: str = "active"
    error: str = ""
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _token_key(token: str) -> str:
    return f"{_TOKEN_PREFIX}:{token}"


def _is_auth_like(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    return any(hint in path for hint in _AUTH_PATH_HINTS)


def _provider_matches(url: str, provider: str) -> bool:
    host = browser_service.extract_domain(url)
    return host == browser_service.extract_domain(provider)


async def create_connect_url(user_id: str, family_id: str, provider: str) -> str:
    """Create a one-time connect URL for a hosted login session."""
    provider = browser_service.extract_domain(provider)
    token = secrets.token_urlsafe(24)
    payload = {
        "user_id": user_id,
        "family_id": family_id,
        "provider": provider,
        "created_at": int(time.time()),
    }
    await redis.set(_token_key(token), json.dumps(payload), ex=CONNECT_TTL_S)
    base_url = settings.public_base_url or ""
    if not base_url:
        return browser_service.get_login_url(provider)
    return f"{base_url}/api/browser-connect/{quote(token, safe='')}"


async def get_token_payload(token: str) -> dict[str, Any] | None:
    raw = await redis.get(_token_key(token))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


async def ensure_session(token: str) -> RemoteBrowserSession:
    """Create or return an active hosted browser session."""
    await _cleanup_stale_sessions()

    async with _sessions_lock:
        existing = _active_sessions.get(token)
        if existing:
            return existing

        payload = await get_token_payload(token)
        if not payload:
            raise ValueError("Connect token expired")

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not available") from exc

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        context = await browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            is_mobile=True,
            has_touch=True,
        )
        page = await context.new_page()
        await page.goto(
            browser_service.get_login_url(payload["provider"]),
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(1.5)

        now = time.time()
        session = RemoteBrowserSession(
            token=token,
            user_id=str(payload["user_id"]),
            family_id=str(payload["family_id"]),
            provider=str(payload["provider"]),
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            created_at=now,
            updated_at=now,
        )
        await _refresh_session_snapshot(session)
        await _maybe_complete_login(session)
        _active_sessions[token] = session
        return session


async def _cleanup_stale_sessions() -> None:
    now = time.time()
    stale_tokens: list[str] = []
    for token, session in list(_active_sessions.items()):
        if (now - session.updated_at) > CONNECT_TTL_S or session.status in {"completed", "error"}:
            stale_tokens.append(token)
    for token in stale_tokens:
        session = _active_sessions.pop(token, None)
        if session:
            await _close_session(session)


async def _close_session(session: RemoteBrowserSession) -> None:
    try:
        await session.browser.close()
    except Exception:
        pass
    try:
        await session.playwright.stop()
    except Exception:
        pass


async def _refresh_session_snapshot(session: RemoteBrowserSession) -> None:
    session.screenshot_png = await session.page.screenshot(type="png", full_page=False)
    session.current_url = session.page.url
    session.updated_at = time.time()


async def _maybe_complete_login(session: RemoteBrowserSession) -> bool:
    if session.status == "completed":
        return True

    storage_state = await session.context.storage_state()
    cookies = storage_state.get("cookies", [])
    has_provider_cookie = any(
        browser_service.extract_domain(str(cookie.get("domain", ""))) == session.provider
        for cookie in cookies
    )
    if (
        has_provider_cookie
        and _provider_matches(session.page.url, session.provider)
        and not _is_auth_like(session.page.url)
    ):
        await browser_service.save_storage_state(
            session.user_id,
            session.family_id,
            session.provider,
            storage_state,
        )
        session.status = "completed"
        session.error = ""
        return True
    return False


def _session_state_payload(session: RemoteBrowserSession) -> dict[str, Any]:
    return {
        "status": session.status,
        "provider": session.provider,
        "current_url": session.current_url,
        "error": session.error,
        "updated_at": int(session.updated_at),
    }


async def get_session_state(token: str) -> dict[str, Any]:
    session = await ensure_session(token)
    async with session.action_lock:
        await _refresh_session_snapshot(session)
        await _maybe_complete_login(session)
        return _session_state_payload(session)


async def get_session_screenshot(token: str) -> bytes:
    session = await ensure_session(token)
    async with session.action_lock:
        if not session.screenshot_png:
            await _refresh_session_snapshot(session)
        return session.screenshot_png


async def apply_action(
    token: str,
    *,
    action: str,
    x: float | None = None,
    y: float | None = None,
    text: str | None = None,
    key: str | None = None,
    delta_y: float | None = None,
) -> dict[str, Any]:
    session = await ensure_session(token)
    async with session.action_lock:
        if session.status == "completed":
            return _session_state_payload(session)

        page = session.page
        if action == "click":
            await page.mouse.click(float(x or 0), float(y or 0))
        elif action == "type":
            if text:
                await page.keyboard.type(text, delay=20)
        elif action == "press":
            mapped_key = _PRESS_KEY_MAP.get((key or "").lower())
            if mapped_key:
                await page.keyboard.press(mapped_key)
        elif action == "scroll":
            await page.mouse.wheel(0, float(delta_y or 0))
        elif action == "back":
            await page.go_back(wait_until="domcontentloaded")
        elif action == "refresh":
            await page.reload(wait_until="domcontentloaded")

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.7)

        await _refresh_session_snapshot(session)
        await _maybe_complete_login(session)
        return _session_state_payload(session)
