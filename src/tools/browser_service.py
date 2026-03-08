"""Browser session service — encrypted cookie persistence and session management.

Manages browser storage_state (cookies + localStorage) for authenticated
web automation. Uses Fernet encryption from src/core/crypto.py.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from src.core.config import settings
from src.core.crypto import decrypt_token, encrypt_token
from src.core.db import async_session
from src.core.models.browser_action_log import BrowserActionLog
from src.core.models.browser_session import UserBrowserSession

logger = logging.getLogger(__name__)

# Sessions expire after 30 days by default
DEFAULT_SESSION_TTL_DAYS = 30

# Mapping of popular domains to their specific login page URLs
_LOGIN_URLS: dict[str, str] = {
    "booking.com": "https://account.booking.com/sign-in",
    "airbnb.com": "https://www.airbnb.com/login",
    "hotels.com": "https://www.hotels.com/account/signin",
    "expedia.com": "https://www.expedia.com/user/signin",
    "agoda.com": "https://www.agoda.com/account/login",
    "trivago.com": "https://www.trivago.com/account/login",
    "kayak.com": "https://www.kayak.com/signin",
    "amazon.com": "https://www.amazon.com/ap/signin",
    "ebay.com": "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn",
    "walmart.com": "https://www.walmart.com/account/login",
    "aliexpress.com": "https://login.aliexpress.com/",
    "skyscanner.com": "https://www.skyscanner.com/sso/login",
    "aviasales.ru": "https://www.aviasales.ru/auth",
    "ostrovok.ru": "https://ostrovok.ru/auth/signin/",
    "ozon.ru": "https://www.ozon.ru/login/",
    "wildberries.ru": "https://www.wildberries.ru/security/login",
    "uber.com": "https://m.uber.com/go/home",
    "lyft.com": "https://ride.lyft.com/",
}


def get_login_url(domain: str) -> str:
    """Get the specific login page URL for a domain.

    Returns the mapped login URL if known, otherwise a generic https://domain URL.
    """
    domain = extract_domain(domain)
    return _LOGIN_URLS.get(domain, f"https://{domain}")


def extract_domain(url_or_site: str) -> str:
    """Normalize URL or site name to a bare domain.

    Examples:
        "https://www.booking.com/hotels?q=NYC" -> "booking.com"
        "booking.com" -> "booking.com"
        "www.amazon.co.uk" -> "amazon.co.uk"
    """
    site = url_or_site.strip().lower()
    # Strip protocol
    site = re.sub(r"^https?://", "", site)
    # Strip path and query
    site = site.split("/")[0].split("?")[0].split("#")[0]
    # Strip www prefix
    site = re.sub(r"^www\.", "", site)
    return site


async def get_storage_state(user_id: str, site: str) -> dict | None:
    """Load and decrypt a saved browser session for a user+site.

    Returns the Playwright storage_state dict, or None if not found/expired.
    """
    domain = extract_domain(site)
    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserBrowserSession).where(
                    UserBrowserSession.user_id == uuid.UUID(user_id),
                    UserBrowserSession.site == domain,
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                return None

            # Check expiration
            if record.expires_at and record.expires_at < datetime.now(UTC):
                logger.info("Browser session expired for user %s on %s", user_id, domain)
                await session.execute(
                    delete(UserBrowserSession).where(UserBrowserSession.id == record.id)
                )
                await session.commit()
                return None

            # Decrypt
            plaintext = decrypt_token(record.storage_state_encrypted)
            return json.loads(plaintext)
    except Exception as e:
        logger.error("Failed to load browser session for %s on %s: %s", user_id, domain, e)
        return None


async def save_storage_state(
    user_id: str,
    family_id: str,
    site: str,
    storage_state: dict,
    ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
) -> None:
    """Encrypt and UPSERT a browser session's storage_state."""
    domain = extract_domain(site)
    plaintext = json.dumps(storage_state)
    encrypted = encrypt_token(plaintext)
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)

    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserBrowserSession).where(
                    UserBrowserSession.user_id == uuid.UUID(user_id),
                    UserBrowserSession.site == domain,
                )
            )
            record = result.scalar_one_or_none()

            if record:
                record.storage_state_encrypted = encrypted
                record.expires_at = expires_at
                record.updated_at = datetime.now(UTC)
            else:
                record = UserBrowserSession(
                    user_id=uuid.UUID(user_id),
                    family_id=uuid.UUID(family_id),
                    site=domain,
                    storage_state_encrypted=encrypted,
                    expires_at=expires_at,
                )
                session.add(record)

            await session.commit()
            logger.info("Saved browser session for user %s on %s", user_id, domain)
    except Exception as e:
        logger.error("Failed to save browser session for %s on %s: %s", user_id, domain, e)
        raise


async def delete_session(user_id: str, site: str) -> bool:
    """Delete a saved browser session. Returns True if a session was deleted."""
    domain = extract_domain(site)
    try:
        async with async_session() as session:
            result = await session.execute(
                delete(UserBrowserSession).where(
                    UserBrowserSession.user_id == uuid.UUID(user_id),
                    UserBrowserSession.site == domain,
                )
            )
            await session.commit()
            return result.rowcount > 0
    except Exception as e:
        logger.error("Failed to delete browser session for %s on %s: %s", user_id, domain, e)
        return False


async def list_user_sessions(user_id: str) -> list[dict[str, str]]:
    """List all saved browser sessions for a user.

    Returns list of dicts with: site, updated_at, expired.
    """
    try:
        async with async_session() as session:
            result = await session.execute(
                select(
                    UserBrowserSession.site,
                    UserBrowserSession.updated_at,
                    UserBrowserSession.expires_at,
                ).where(UserBrowserSession.user_id == uuid.UUID(user_id))
            )
            rows = result.all()

        now = datetime.now(UTC)
        return [
            {
                "site": row.site,
                "updated_at": row.updated_at.strftime("%Y-%m-%d") if row.updated_at else "",
                "expired": bool(row.expires_at and row.expires_at < now),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("Failed to list sessions for %s: %s", user_id, e)
        return []


async def log_action(
    user_id: str,
    action_type: str,
    url: str | None = None,
    session_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Write an entry to the browser_action_logs table."""
    try:
        async with async_session() as session:
            log_entry = BrowserActionLog(
                user_id=uuid.UUID(user_id),
                session_id=uuid.UUID(session_id) if session_id else None,
                action_type=action_type,
                url=url,
                details=details,
            )
            session.add(log_entry)
            await session.commit()
    except Exception as e:
        logger.warning("Failed to log browser action: %s", e)


async def execute_with_session(
    user_id: str,
    family_id: str,
    site: str,
    task: str,
    max_steps: int = 15,
    timeout: float = 120,
) -> dict[str, Any]:
    """Execute a browser task with saved cookies.

    1. Load encrypted storage_state from DB
    2. Try OpenAI Computer Use first when enabled
    3. Fallback to Browser-Use if needed
    4. Save updated cookies back to DB
    5. Log the action

    Returns dict with success, result, engine keys.
    """
    import os
    import tempfile

    domain = extract_domain(site)
    storage_state = await get_storage_state(user_id, domain)

    if settings.ff_browser_computer_use and settings.openai_api_key:
        from src.tools import computer_use_service

        cu_result = await computer_use_service.execute_task(
            storage_state=storage_state,
            site=domain,
            task=task,
            max_steps=max(max_steps, 25),
            timeout=max(timeout, 180),
        )
        if cu_result.get("storage_state"):
            try:
                await save_storage_state(
                    user_id,
                    family_id,
                    domain,
                    cu_result["storage_state"],
                )
            except Exception as e:
                logger.warning("Failed to save updated cookies after computer-use task: %s", e)

        cu_text = str(cu_result.get("result", ""))
        if cu_result.get("success") or cu_text in {"LOGIN_REQUIRED", "CAPTCHA_DETECTED"}:
            await log_action(
                user_id=user_id,
                action_type="browser_task",
                url=cu_result.get("url") or f"https://{domain}",
                details={
                    "task": task[:200],
                    "success": bool(cu_result.get("success")),
                    "engine": cu_result.get("engine"),
                },
            )
            return cu_result

    try:
        from browser_use import Agent as BrowserAgent
        from browser_use import BrowserProfile
        from browser_use import ChatAnthropic as BrowserUseChatAnthropic
    except ImportError:
        return {
            "success": False,
            "result": "Browser-Use is not available.",
            "engine": "browser_use",
        }

    # Ensure config dir
    if not os.getenv("BROWSER_USE_CONFIG_DIR"):
        default_dir = os.path.join(tempfile.gettempdir(), "browseruse")
        os.makedirs(default_dir, exist_ok=True)
        os.environ["BROWSER_USE_CONFIG_DIR"] = default_dir

    try:
        llm = BrowserUseChatAnthropic(model="claude-sonnet-4-6")
        profile_kwargs: dict[str, Any] = {
            "headless": True,
            "enable_default_extensions": False,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
            ],
        }
        if storage_state:
            profile_kwargs["storage_state"] = storage_state
            profile_kwargs["user_data_dir"] = None  # avoid conflict with storage_state

        browser_profile = BrowserProfile(**profile_kwargs)
        agent = BrowserAgent(task=task, llm=llm, browser_profile=browser_profile)

        history = await asyncio.wait_for(
            agent.run(max_steps=max_steps),
            timeout=timeout,
        )

        # Extract result
        final = history.final_result() if hasattr(history, "final_result") else None
        if not final:
            parts = []
            for ar in history.all_results:
                if ar.extracted_content:
                    parts.append(ar.extracted_content)
            final = "\n".join(parts) if parts else str(history)

        # Try to save updated cookies from the browser context
        try:
            browser = getattr(agent, "browser", None)
            if browser:
                context = getattr(browser, "context", None) or getattr(
                    browser, "browser_context", None
                )
                if context:
                    new_state = await context.storage_state()
                    if new_state:
                        await save_storage_state(user_id, family_id, domain, new_state)
        except Exception as e:
            logger.warning("Failed to save updated cookies after task: %s", e)

        # Log the action
        await log_action(
            user_id=user_id,
            action_type="browser_task",
            url=f"https://{domain}",
            details={"task": task[:200], "success": True},
        )

        return {
            "success": bool(final),
            "result": final or "Browser task completed but returned no data.",
            "engine": "browser_use",
        }

    except TimeoutError:
        await log_action(
            user_id=user_id,
            action_type="browser_task_timeout",
            url=f"https://{domain}",
            details={"task": task[:200]},
        )
        return {
            "success": False,
            "result": f"Browser task timed out after {timeout}s.",
            "engine": "browser_use",
        }
    except Exception as e:
        logger.exception("Browser task with session failed: %s", task[:100])
        await log_action(
            user_id=user_id,
            action_type="browser_task_error",
            url=f"https://{domain}",
            details={"task": task[:200], "error": str(e)[:200]},
        )
        return {
            "success": False,
            "result": f"Browser task failed: {e}",
            "engine": "browser_use",
        }

