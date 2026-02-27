"""Interactive browser login flow via Telegram.

Multi-step login using Redis conversation state (same pattern as onboarding).

States: idle → awaiting_email → awaiting_password → awaiting_2fa → done/failed
Redis key: browser_login:{user_id} (TTL 300s)
Browser sessions: module-level dict (in-memory, cleaned up on done/TTL)

Security:
- Passwords never stored in Redis, DB, or logs — local variable only
- Password message deleted from Telegram immediately
- Browser-Use sensitive_data param redacts from LLM traces
- Login result detection via Gemini Flash screenshot analysis
"""

import asyncio
import json
import logging
from typing import Any

from src.core.db import redis
from src.tools import browser_service

logger = logging.getLogger(__name__)

LOGIN_FLOW_TTL = 300  # 5 minutes
_REDIS_PREFIX = "browser_login"

# In-memory browser sessions for active login flows
# key: user_id, value: {"browser": ..., "context": ..., "page": ...}
_active_sessions: dict[str, Any] = {}


async def get_login_state(user_id: str) -> dict | None:
    """Get the current login flow state from Redis."""
    raw = await redis.get(f"{_REDIS_PREFIX}:{user_id}")
    if not raw:
        return None
    return json.loads(raw)


async def _set_login_state(user_id: str, state: dict) -> None:
    """Store login flow state in Redis."""
    await redis.set(
        f"{_REDIS_PREFIX}:{user_id}",
        json.dumps(state),
        ex=LOGIN_FLOW_TTL,
    )


async def _clear_login_state(user_id: str) -> None:
    """Clear login flow state from Redis and cleanup browser."""
    await redis.delete(f"{_REDIS_PREFIX}:{user_id}")
    await _cleanup_browser(user_id)


async def _cleanup_browser(user_id: str) -> None:
    """Close and remove in-memory browser session."""
    session_data = _active_sessions.pop(user_id, None)
    if session_data:
        try:
            browser = session_data.get("browser")
            if browser:
                await browser.close()
        except Exception as e:
            logger.warning("Failed to close login browser for %s: %s", user_id, e)


async def start_login(
    user_id: str,
    family_id: str,
    site: str,
    task: str,
) -> dict[str, Any]:
    """Start an interactive login flow for a website.

    Opens the login page, takes a screenshot, and returns instructions
    for the user to enter their email.

    Returns:
        dict with keys: action ("ask_email"|"error"), text, screenshot_bytes
    """
    domain = browser_service.extract_domain(site)
    login_url = f"https://{domain}"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "action": "error",
            "text": "Playwright is not available for login flow.",
        }

    try:
        # Launch browser and navigate to login page
        pw = await async_playwright().__aenter__()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-infobars",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)

        # Take screenshot
        screenshot = await page.screenshot(type="png")

        # Store browser session in memory
        _active_sessions[user_id] = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
        }

        # Store flow state in Redis (NO sensitive data)
        await _set_login_state(user_id, {
            "step": "awaiting_email",
            "site": domain,
            "family_id": family_id,
            "task": task,
            "login_url": login_url,
        })

        return {
            "action": "ask_email",
            "text": (
                f"I need to log you into <b>{domain}</b>.\n\n"
                "Please enter your email/username for this site:"
            ),
            "screenshot_bytes": screenshot,
        }

    except Exception as e:
        logger.error("Failed to start login flow for %s: %s", domain, e)
        await _cleanup_browser(user_id)
        return {
            "action": "error",
            "text": f"Could not open {domain}: {e}",
        }


async def handle_step(
    user_id: str,
    family_id: str,
    message_text: str,
    gateway: Any = None,
    chat_id: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Handle the next step in the login flow.

    Args:
        user_id: User ID
        family_id: Family ID
        message_text: User's input (email, password, or 2FA code)
        gateway: Gateway instance for deleting password messages
        chat_id: Chat ID for message deletion
        message_id: Message ID for deletion (password security)

    Returns:
        dict with keys: action, text, screenshot_bytes (optional)
        action values: "ask_password", "ask_2fa", "login_success",
                       "login_failed", "error", "no_flow"
    """
    state = await get_login_state(user_id)
    if not state:
        return {"action": "no_flow", "text": None}

    step = state.get("step", "")
    session_data = _active_sessions.get(user_id)

    if step == "awaiting_email":
        return await _handle_email_step(user_id, state, message_text, session_data)
    elif step == "awaiting_password":
        return await _handle_password_step(
            user_id, state, message_text, session_data, gateway, chat_id, message_id
        )
    elif step == "awaiting_2fa":
        return await _handle_2fa_step(user_id, state, message_text, session_data)
    else:
        await _clear_login_state(user_id)
        return {"action": "error", "text": "Unknown login step."}


async def _handle_email_step(
    user_id: str,
    state: dict,
    email: str,
    session_data: dict | None,
) -> dict[str, Any]:
    """Type email into the login form and ask for password."""
    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": "Browser session expired. Try again."}

    page = session_data["page"]

    try:
        # Try common email/username input selectors
        typed = False
        for selector in [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[name="login"]',
            'input[id="email"]',
            'input[id="username"]',
            'input[id="login"]',
            'input[type="text"]',
        ]:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.fill(email)
                    typed = True
                    break
            except Exception:
                continue

        if not typed:
            # Fallback: focus first input and type
            await page.keyboard.press("Tab")
            await page.keyboard.type(email, delay=50)

        # Try to submit / click next
        await _click_next_button(page)
        await asyncio.sleep(2)

        screenshot = await page.screenshot(type="png")

        state["step"] = "awaiting_password"
        await _set_login_state(user_id, state)

        return {
            "action": "ask_password",
            "text": (
                "Now enter your <b>password</b>.\n\n"
                "Your message will be <b>deleted immediately</b> for security."
            ),
            "screenshot_bytes": screenshot,
        }

    except Exception as e:
        logger.error("Email step failed for %s: %s", user_id, e)
        await _clear_login_state(user_id)
        return {"action": "error", "text": f"Failed to enter email: {e}"}


async def _handle_password_step(
    user_id: str,
    state: dict,
    password: str,
    session_data: dict | None,
    gateway: Any = None,
    chat_id: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Type password, submit login, and check result.

    Password is used as a local variable ONLY — never stored anywhere.
    The user's Telegram message containing the password is deleted immediately.
    """
    # DELETE the password message from Telegram FIRST
    if gateway and chat_id and message_id:
        try:
            await gateway.delete_message(chat_id, message_id)
        except Exception as e:
            logger.warning("Failed to delete password message: %s", e)

    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": "Browser session expired. Try again."}

    page = session_data["page"]

    try:
        # Type password
        typed = False
        for selector in [
            'input[type="password"]',
            'input[name="password"]',
            'input[id="password"]',
        ]:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.fill(password)
                    typed = True
                    break
            except Exception:
                continue

        if not typed:
            await page.keyboard.type(password, delay=50)

        # Password used — clear from local scope as soon as possible
        password = ""  # noqa: F841

        # Submit login
        await _click_submit_button(page)
        await asyncio.sleep(3)

        # Analyze login result
        screenshot = await page.screenshot(type="png")
        login_result = await _analyze_login_result(screenshot)
        logger.info(
            "Login result for %s on %s: %s", user_id, state["site"], login_result
        )

        if login_result == "success":
            # Save cookies
            context = session_data["context"]
            storage_state = await context.storage_state()
            site = state["site"]
            family_id = state["family_id"]
            task = state["task"]

            await browser_service.save_storage_state(user_id, family_id, site, storage_state)
            logger.info(
                "Cookies saved for %s on %s (%d cookies)",
                user_id, site, len(storage_state.get("cookies", [])),
            )
            await browser_service.log_action(
                user_id=user_id,
                action_type="login_success",
                url=f"https://{site}",
            )
            await _clear_login_state(user_id)

            return {
                "action": "login_success",
                "text": (
                    f"Logged in to <b>{site}</b> successfully! "
                    "Your session is saved securely.\n\n"
                    "Now executing your task..."
                ),
                "task": task,
                "site": site,
            }

        elif login_result == "2fa":
            state["step"] = "awaiting_2fa"
            await _set_login_state(user_id, state)
            return {
                "action": "ask_2fa",
                "text": "Two-factor authentication required. Enter the code:",
                "screenshot_bytes": screenshot,
            }

        else:
            await browser_service.log_action(
                user_id=user_id,
                action_type="login_failed",
                url=f"https://{state['site']}",
            )
            await _clear_login_state(user_id)
            return {
                "action": "login_failed",
                "text": (
                    "Login failed. Please check your credentials and try again.\n"
                    "Your password was not stored anywhere."
                ),
                "screenshot_bytes": screenshot,
            }

    except Exception as e:
        logger.error("Password step failed for %s: %s", user_id, e)
        await _clear_login_state(user_id)
        return {"action": "error", "text": f"Login failed: {e}"}


async def _handle_2fa_step(
    user_id: str,
    state: dict,
    code: str,
    session_data: dict | None,
) -> dict[str, Any]:
    """Enter 2FA code and check login result."""
    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": "Browser session expired. Try again."}

    page = session_data["page"]

    try:
        # Type 2FA code
        typed = False
        for selector in [
            'input[name="code"]',
            'input[name="otp"]',
            'input[name="totp"]',
            'input[type="tel"]',
            'input[inputmode="numeric"]',
            'input[autocomplete="one-time-code"]',
        ]:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.fill(code)
                    typed = True
                    break
            except Exception:
                continue

        if not typed:
            await page.keyboard.type(code, delay=50)

        await _click_submit_button(page)
        await asyncio.sleep(3)

        screenshot = await page.screenshot(type="png")
        login_result = await _analyze_login_result(screenshot)

        if login_result == "success":
            context = session_data["context"]
            storage_state = await context.storage_state()
            site = state["site"]
            family_id = state["family_id"]
            task = state["task"]

            await browser_service.save_storage_state(user_id, family_id, site, storage_state)
            await browser_service.log_action(
                user_id=user_id,
                action_type="login_success_2fa",
                url=f"https://{site}",
            )
            await _clear_login_state(user_id)

            return {
                "action": "login_success",
                "text": (
                    f"Logged in to <b>{site}</b> successfully! "
                    "Your session is saved securely.\n\n"
                    "Now executing your task..."
                ),
                "task": task,
                "site": site,
            }
        else:
            await _clear_login_state(user_id)
            return {
                "action": "login_failed",
                "text": "2FA verification failed. Please try again.",
                "screenshot_bytes": screenshot,
            }

    except Exception as e:
        logger.error("2FA step failed for %s: %s", user_id, e)
        await _clear_login_state(user_id)
        return {"action": "error", "text": f"2FA failed: {e}"}


async def cancel_login(user_id: str) -> None:
    """Cancel an active login flow."""
    await _clear_login_state(user_id)


async def _click_next_button(page: Any) -> None:
    """Try to click a 'Next' / 'Continue' button on login forms."""
    for selector in [
        'button[type="submit"]',
        'input[type="submit"]',
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Далее')",
        "button:has-text('Продолжить')",
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
    ]:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=1000):
                await el.click()
                return
        except Exception:
            continue
    # Fallback: press Enter
    await page.keyboard.press("Enter")


async def _click_submit_button(page: Any) -> None:
    """Try to click submit/login button."""
    for selector in [
        'button[type="submit"]',
        'input[type="submit"]',
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
        "button:has-text('Login')",
        "button:has-text('Войти')",
        "button:has-text('Submit')",
        "button:has-text('Verify')",
        "button:has-text('Confirm')",
    ]:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=1000):
                await el.click()
                return
        except Exception:
            continue
    await page.keyboard.press("Enter")


async def _analyze_login_result(screenshot: bytes) -> str:
    """Analyze a screenshot to determine login outcome.

    Uses Gemini Flash to classify: 'success', '2fa', 'failed', 'captcha'.
    Falls back to 'failed' if analysis fails.
    """
    try:
        import base64

        from google.genai import types

        from src.core.llm.clients import google_client

        client = google_client()
        b64 = base64.b64encode(screenshot).decode()

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/png",
                                data=base64.b64decode(b64),
                            )
                        ),
                        types.Part(
                            text=(
                                "Analyze this screenshot of a website after a login attempt. "
                                "Classify the result as exactly one of:\n"
                                "- 'success' — user is logged in (dashboard, profile, "
                                "welcome message, account page)\n"
                                "- '2fa' — two-factor authentication is required "
                                "(OTP, SMS code, authenticator)\n"
                                "- 'captcha' — CAPTCHA challenge shown\n"
                                "- 'failed' — login failed (wrong password, error message)\n\n"
                                "Respond with ONLY one word: success, 2fa, captcha, or failed."
                            ),
                        ),
                    ]
                )
            ],
            config=types.GenerateContentConfig(max_output_tokens=10),
        )

        result_text = response.text.strip().lower()
        if result_text in ("success", "2fa", "captcha", "failed"):
            return result_text
        # Try to extract from response
        for keyword in ("success", "2fa", "captcha", "failed"):
            if keyword in result_text:
                return keyword
        return "failed"

    except Exception as e:
        logger.warning("Login result analysis failed: %s", e)
        return "failed"
