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
MOBILE_VIEWPORT_WIDTH = 430
MOBILE_VIEWPORT_HEIGHT = 932
DESKTOP_VIEWPORT_WIDTH = 1440
DESKTOP_VIEWPORT_HEIGHT = 1100
_TOKEN_PREFIX = "browser_connect"
_AUTH_PATH_HINTS = ("/login", "/signin", "/sign-in", "/auth", "/challenge", "/verify")
_GENERIC_LOGIN_MARKERS = (
    " login",
    " sign in",
    " log in",
    " continue with google",
    " continue with apple",
    " continue with facebook",
    " forgot password",
    " phone number",
    " email address",
)
_PROVIDER_LOGIN_MARKERS: dict[str, tuple[str, ...]] = {
    "uber.com": (
        "login",
        "sign in",
        "log in",
        "continue with google",
        "continue with apple",
        "continue with facebook",
    ),
}
_PROVIDER_AUTH_MARKERS: dict[str, tuple[str, ...]] = {
    "uber.com": (
        "where to?",
        "activity",
        "services",
        "account",
        "wallet",
        "home",
    ),
}
_PRESS_KEY_MAP = {
    "enter": "Enter",
    "tab": "Tab",
    "backspace": "Backspace",
    "escape": "Escape",
    "space": " ",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "home": "Home",
    "end": "End",
    "delete": "Delete",
}
# URL schemes that must NEVER be followed as popups
_SKIP_POPUP_SCHEMES = ("about:", "data:", "blob:", "javascript:")
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
    is_mobile: bool = False
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class BrowserClientProfile:
    viewport: dict[str, int]
    is_mobile: bool
    has_touch: bool


def _token_key(token: str) -> str:
    return f"{_TOKEN_PREFIX}:{token}"


def _is_auth_like(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    return any(hint in path for hint in _AUTH_PATH_HINTS)


def _provider_matches(url: str, provider: str) -> bool:
    host = browser_service.extract_domain(url)
    return host == browser_service.extract_domain(provider)


def _is_mobile_user_agent(user_agent: str | None) -> bool:
    lowered = (user_agent or "").lower()
    mobile_markers = (
        "iphone",
        "ipad",
        "ipod",
        "android",
        "mobile",
        "windows phone",
    )
    return any(marker in lowered for marker in mobile_markers)


def _build_client_profile(user_agent: str | None) -> BrowserClientProfile:
    if _is_mobile_user_agent(user_agent):
        return BrowserClientProfile(
            viewport={"width": MOBILE_VIEWPORT_WIDTH, "height": MOBILE_VIEWPORT_HEIGHT},
            is_mobile=True,
            has_touch=True,
        )
    return BrowserClientProfile(
        viewport={"width": DESKTOP_VIEWPORT_WIDTH, "height": DESKTOP_VIEWPORT_HEIGHT},
        is_mobile=False,
        has_touch=False,
    )


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


async def ensure_session(token: str, *, user_agent: str | None = None) -> RemoteBrowserSession:
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
        _args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        try:
            browser = await playwright.chromium.launch(
                channel="chrome",
                headless=True,
                args=_args,
            )
            logger.info("Launched Google Chrome (channel='chrome')")
        except Exception as exc:
            logger.warning("Chrome launch failed (%s), falling back to Chromium", exc)
            browser = await playwright.chromium.launch(headless=True, args=_args)
        profile = _build_client_profile(user_agent)
        context = await browser.new_context(
            viewport=profile.viewport,
            is_mobile=profile.is_mobile,
            has_touch=profile.has_touch,
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
            is_mobile=profile.is_mobile,
        )

        # Auto-follow popups (Google OAuth, Apple Sign-in, etc.).
        # When a button opens a new window/popup, switch session.page to it
        # so screenshots and subsequent clicks target the popup.
        def _on_new_page(new_page: Any) -> None:
            asyncio.ensure_future(_follow_popup(session, new_page))

        context.on("page", _on_new_page)

        await _refresh_session_snapshot(session)
        await _maybe_complete_login(session)
        _active_sessions[token] = session
        return session


async def _follow_popup(session: RemoteBrowserSession, new_page: Any) -> None:
    """Switch session to a popup page (e.g. Google/Apple OAuth window).

    Filters out blank/data/blob pages and only follows real HTTP(S) URLs.
    Acquires action_lock so concurrent apply_action calls see the new page.
    """
    try:
        await new_page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass

    url = new_page.url or ""
    # Reject blank, data-URI, blob, and javascript: "pages" — these are
    # analytics pixels or attack vectors, not real login pages.
    if not url or any(url.startswith(s) for s in _SKIP_POPUP_SCHEMES):
        logger.debug("browser-connect %s: ignoring popup with url=%r", session.token[:8], url)
        return

    if session.status != "active":
        return

    async with session.action_lock:
        session.page = new_page
        logger.info("browser-connect %s: switched to popup %s", session.token[:8], url)
        await _refresh_session_snapshot(session)


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
    try:
        session.screenshot_png = await session.page.screenshot(type="png", full_page=False)
        session.current_url = session.page.url
    except Exception as e:
        logger.warning("Failed to refresh browser-connect snapshot for %s: %s", session.token, e)
        if not session.error:
            session.error = str(e)
    session.updated_at = time.time()


async def _page_text(session: RemoteBrowserSession) -> str:
    try:
        text = await session.page.text_content("body")
    except Exception:
        return ""
    return (text or "").strip().lower()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = f" {text} "
    return any(marker in lowered for marker in markers)


async def _looks_authenticated(session: RemoteBrowserSession) -> bool:
    body_text = await _page_text(session)
    provider = session.provider

    login_markers = _GENERIC_LOGIN_MARKERS + _PROVIDER_LOGIN_MARKERS.get(provider, ())
    if body_text and _contains_any(body_text, login_markers):
        return False

    auth_markers = _PROVIDER_AUTH_MARKERS.get(provider, ())
    if auth_markers:
        return _contains_any(body_text, auth_markers)

    return True


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
        and await _looks_authenticated(session)
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


async def get_session_state(token: str, *, user_agent: str | None = None) -> dict[str, Any]:
    session = await ensure_session(token, user_agent=user_agent)
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
        cx, cy = float(x or 0), float(y or 0)
        if action == "click":
            # Mobile contexts respond better to tap() than mouse.click()
            if session.is_mobile:
                await page.tap(cx, cy)
            else:
                await page.mouse.click(cx, cy)
        elif action == "type":
            if text:
                await page.keyboard.type(text, delay=20)
        elif action == "press":
            mapped_key = _PRESS_KEY_MAP.get((key or "").lower())
            if mapped_key:
                await page.keyboard.press(mapped_key)
            else:
                logger.debug("browser-connect: unmapped key %r — ignored", key)
        elif action == "scroll":
            await page.mouse.wheel(0, float(delta_y or 0))
        elif action == "back":
            await page.go_back(wait_until="domcontentloaded")
        elif action == "refresh":
            await page.reload(wait_until="domcontentloaded")

        # Wait for navigation; 12s covers slow OAuth redirects and SPAs
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=12_000)
        except Exception:
            pass
        await asyncio.sleep(1.2)

        await _refresh_session_snapshot(session)
        await _maybe_complete_login(session)
        return _session_state_payload(session)
