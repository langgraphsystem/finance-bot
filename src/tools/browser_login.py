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
import secrets
import time
from typing import Any

from src.core.db import redis
from src.tools import browser_service

logger = logging.getLogger(__name__)

LOGIN_FLOW_TTL = 300  # 5 minutes
_REDIS_PREFIX = "browser_login"

# In-memory browser sessions for active login flows
# key: user_id, value: {"browser": ..., "context": ..., "page": ...}
_active_sessions: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Site-specific login configuration
# ---------------------------------------------------------------------------

_SITE_LOGIN_CONFIG: dict[str, dict[str, Any]] = {
    "uber.com": {
        "credential_type": "phone",
        "input_selectors": [
            'input[name="phoneNumber"]',
            'input[id="PHONE_NUMBER_or_EMAIL_ADDRESS"]',
            'input[type="tel"]',
            'input[type="text"]',
        ],
    },
    "ubereats.com": {
        "credential_type": "phone",
        "input_selectors": [
            'input[name="phoneNumber"]',
            'input[id="PHONE_NUMBER_or_EMAIL_ADDRESS"]',
            'input[type="tel"]',
            'input[type="text"]',
        ],
    },
    "doordash.com": {
        "credential_type": "email",
    },
    "grubhub.com": {
        "credential_type": "email",
    },
}

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "ask_email": "I need to log you into <b>{site}</b>.\n\nPlease enter your email/username:",
        "ask_phone": "I need to log you into <b>{site}</b>.\n\nPlease enter your phone number:",
        "ask_password": (
            "Now enter your <b>password</b>.\n\n"
            "Your message will be <b>deleted immediately</b> for security."
        ),
        "ask_password_google": (
            "This is <b>Google login</b>. Enter your Google password:\n\n"
            "Your message will be <b>deleted immediately</b>."
        ),
        "ask_password_apple": (
            "This is <b>Apple login</b>. Enter your Apple ID password:\n\n"
            "Your message will be <b>deleted immediately</b>."
        ),
        "ask_password_oauth": (
            "OAuth login page opened. Enter your <b>password</b>.\n\n"
            "Your message will be <b>deleted immediately</b>."
        ),
        "ask_2fa": "Two-factor authentication required. Enter the code:",
        "login_success": (
            "Logged in to <b>{site}</b> successfully! "
            "Session saved.\n\nNow executing your task..."
        ),
        "login_failed": (
            "Login failed. Please check your credentials and try again.\n"
            "Your password was not stored anywhere."
        ),
        "2fa_failed": "2FA verification failed. Please try again.",
        "captcha_detected": (
            "CAPTCHA detected. Open the browser below to solve it, "
            "then I'll continue automatically."
        ),
        "session_expired": "Browser session expired. Try again.",
        "open_failed": "Could not open {site}: {error}",
        "playwright_missing": "Playwright is not available for login flow.",
        "btn_solve_captcha": "Open browser",
    },
    "ru": {
        "ask_email": (
            "Нужно войти в <b>{site}</b>.\n\nВведите email или имя пользователя:"
        ),
        "ask_phone": "Нужно войти в <b>{site}</b>.\n\nВведите номер телефона:",
        "ask_password": (
            "Теперь введите <b>пароль</b>.\n\n"
            "Сообщение будет <b>удалено сразу</b> для безопасности."
        ),
        "ask_password_google": (
            "Это <b>вход через Google</b>. Введите пароль Google:\n\n"
            "Сообщение будет <b>удалено сразу</b>."
        ),
        "ask_password_apple": (
            "Это <b>вход через Apple</b>. Введите пароль Apple ID:\n\n"
            "Сообщение будет <b>удалено сразу</b>."
        ),
        "ask_password_oauth": (
            "Открыта страница OAuth. Введите <b>пароль</b>.\n\n"
            "Сообщение будет <b>удалено сразу</b>."
        ),
        "ask_2fa": "Требуется двухфакторная аутентификация. Введите код:",
        "login_success": (
            "Вход в <b>{site}</b> выполнен! "
            "Сессия сохранена.\n\nВыполняю задачу..."
        ),
        "login_failed": (
            "Вход не удался. Проверьте данные и попробуйте снова.\n"
            "Пароль нигде не сохранён."
        ),
        "2fa_failed": "Проверка 2FA не пройдена. Попробуйте ещё раз.",
        "captcha_detected": (
            "Обнаружена CAPTCHA. Откройте браузер ниже, чтобы решить её, "
            "а я продолжу автоматически."
        ),
        "session_expired": "Сессия браузера истекла. Попробуйте снова.",
        "open_failed": "Не удалось открыть {site}: {error}",
        "playwright_missing": "Playwright недоступен.",
        "btn_solve_captcha": "Открыть браузер",
    },
    "es": {
        "ask_email": (
            "Necesito iniciar sesión en <b>{site}</b>.\n\n"
            "Ingresa tu email o nombre de usuario:"
        ),
        "ask_phone": (
            "Necesito iniciar sesión en <b>{site}</b>.\n\n"
            "Ingresa tu número de teléfono:"
        ),
        "ask_password": (
            "Ahora ingresa tu <b>contraseña</b>.\n\n"
            "Tu mensaje será <b>eliminado inmediatamente</b> por seguridad."
        ),
        "ask_password_google": (
            "Inicio de sesión con <b>Google</b>. Ingresa tu contraseña de Google:\n\n"
            "Tu mensaje será <b>eliminado inmediatamente</b>."
        ),
        "ask_password_apple": (
            "Inicio de sesión con <b>Apple</b>. Ingresa tu contraseña de Apple ID:\n\n"
            "Tu mensaje será <b>eliminado inmediatamente</b>."
        ),
        "ask_password_oauth": (
            "Página OAuth abierta. Ingresa tu <b>contraseña</b>.\n\n"
            "Tu mensaje será <b>eliminado inmediatamente</b>."
        ),
        "ask_2fa": "Se requiere autenticación de dos factores. Ingresa el código:",
        "login_success": (
            "Sesión en <b>{site}</b> iniciada con éxito! "
            "Sesión guardada.\n\nEjecutando tu tarea..."
        ),
        "login_failed": (
            "Inicio de sesión fallido. Verifica tus datos e intenta de nuevo.\n"
            "Tu contraseña no fue almacenada."
        ),
        "2fa_failed": "Verificación 2FA fallida. Intenta de nuevo.",
        "captcha_detected": (
            "CAPTCHA detectado. Abre el navegador a continuación para resolverlo, "
            "y continuaré automáticamente."
        ),
        "session_expired": "Sesión del navegador expirada. Intenta de nuevo.",
        "open_failed": "No se pudo abrir {site}: {error}",
        "playwright_missing": "Playwright no está disponible.",
        "btn_solve_captcha": "Abrir navegador",
    },
}


def _t(key: str, lang: str, **kwargs: Any) -> str:
    """Get translated string."""
    strings = _STRINGS.get(lang, _STRINGS["en"])
    template = strings.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def _get_site_config(domain: str) -> dict[str, Any]:
    """Get site-specific login config or defaults."""
    return _SITE_LOGIN_CONFIG.get(domain, {})


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
    language: str = "en",
) -> dict[str, Any]:
    """Start an interactive login flow for a website.

    Opens the login page, takes a screenshot, and returns instructions
    for the user to enter their email/phone (depending on site config).

    Returns:
        dict with keys: action ("ask_email"|"ask_phone"|"error"), text, screenshot_bytes
    """
    domain = browser_service.extract_domain(site)
    site_config = _get_site_config(domain)
    credential_type = site_config.get("credential_type", "email")
    login_url = browser_service.get_login_url(domain)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "action": "error",
            "text": _t("playwright_missing", language),
        }

    try:
        # Launch browser and navigate to login page
        pw = await async_playwright().__aenter__()
        _launch_args = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-infobars",
            ],
        }
        browser = await pw.chromium.launch(channel="chrome", **_launch_args)
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
        action = "ask_phone" if credential_type == "phone" else "ask_email"
        await _set_login_state(user_id, {
            "step": "awaiting_email",
            "site": domain,
            "family_id": family_id,
            "task": task,
            "language": language,
            "login_url": login_url,
            "credential_type": credential_type,
        })

        prompt_key = "ask_phone" if credential_type == "phone" else "ask_email"
        return {
            "action": action,
            "text": _t(prompt_key, language, site=domain),
            "screenshot_bytes": screenshot,
        }

    except Exception as e:
        logger.error("Failed to start login flow for %s: %s", domain, e)
        await _cleanup_browser(user_id)
        return {
            "action": "error",
            "text": _t("open_failed", language, site=domain, error=str(e)),
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
    """Type email/phone into the login form and ask for password."""
    lang = state.get("language", "en")
    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": _t("session_expired", lang)}

    page = session_data["page"]
    context = session_data["context"]
    site_config = _get_site_config(state.get("site", ""))

    try:
        # Use site-specific selectors first, then generic ones
        site_selectors = site_config.get("input_selectors", [])
        default_selectors = [
            "#identifierId",  # Google login
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[name="login"]',
            'input[id="email"]',
            'input[id="username"]',
            'input[id="login"]',
            'input[type="text"]',
        ]
        all_selectors = site_selectors + [
            s for s in default_selectors if s not in site_selectors
        ]

        typed = False
        for selector in all_selectors:
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

        # Listen for popup (OAuth popup windows like Google/Apple)
        popup_page = None

        async def _on_popup(p: Any) -> None:
            nonlocal popup_page
            popup_page = p

        context.on("page", _on_popup)

        # Try to submit / click next
        await _click_next_button(page)

        # Wait for navigation (networkidle is safer than fixed sleep)
        try:
            await page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            await asyncio.sleep(2.5)

        context.remove_listener("page", _on_popup)

        # OAuth popup detected — switch to handling the popup page
        if popup_page:
            try:
                await popup_page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            session_data["page"] = popup_page
            state["oauth_popup"] = True
            state["step"] = "awaiting_password"
            await _set_login_state(user_id, state)
            screenshot = await popup_page.screenshot(type="png")
            url = popup_page.url
            if "google.com" in url:
                prompt_key = "ask_password_google"
            elif "apple.com" in url:
                prompt_key = "ask_password_apple"
            else:
                prompt_key = "ask_password_oauth"
            return {
                "action": "ask_password",
                "text": _t(prompt_key, lang),
                "screenshot_bytes": screenshot,
            }

        # Check if the page redirected to a known OAuth provider
        current_url = page.url
        if "accounts.google.com" in current_url:
            state["step"] = "awaiting_password"
            state["oauth_provider"] = "google"
            await _set_login_state(user_id, state)
            screenshot = await page.screenshot(type="png")
            return {
                "action": "ask_password",
                "text": _t("ask_password_google", lang),
                "screenshot_bytes": screenshot,
            }
        if "appleid.apple.com" in current_url:
            state["step"] = "awaiting_password"
            state["oauth_provider"] = "apple"
            await _set_login_state(user_id, state)
            screenshot = await page.screenshot(type="png")
            return {
                "action": "ask_password",
                "text": _t("ask_password_apple", lang),
                "screenshot_bytes": screenshot,
            }

        screenshot = await page.screenshot(type="png")

        state["step"] = "awaiting_password"
        await _set_login_state(user_id, state)

        return {
            "action": "ask_password",
            "text": _t("ask_password", lang),
            "screenshot_bytes": screenshot,
        }

    except Exception as e:
        logger.error("Email step failed for %s: %s", user_id, e)
        await _clear_login_state(user_id)
        return {"action": "error", "text": f"Failed to enter credentials: {e}"}


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
    lang = state.get("language", "en")

    # DELETE the password message from Telegram FIRST
    if gateway and chat_id and message_id:
        try:
            await gateway.delete_message(chat_id, message_id)
        except Exception as e:
            logger.warning("Failed to delete password message: %s", e)

    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": _t("session_expired", lang)}

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
                "text": _t("login_success", lang, site=site),
                "task": task,
                "site": site,
            }

        elif login_result == "2fa":
            state["step"] = "awaiting_2fa"
            await _set_login_state(user_id, state)
            return {
                "action": "ask_2fa",
                "text": _t("ask_2fa", lang),
                "screenshot_bytes": screenshot,
            }

        elif login_result == "captcha":
            # Escalate to browser-connect for manual CAPTCHA solving
            escalation = await _escalate_to_browser_connect(user_id, state, session_data)
            return escalation

        else:
            await browser_service.log_action(
                user_id=user_id,
                action_type="login_failed",
                url=f"https://{state['site']}",
            )
            await _clear_login_state(user_id)
            return {
                "action": "login_failed",
                "text": _t("login_failed", lang),
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
    lang = state.get("language", "en")
    if not session_data:
        await _clear_login_state(user_id)
        return {"action": "error", "text": _t("session_expired", lang)}

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
                "text": _t("login_success", lang, site=site),
                "task": task,
                "site": site,
            }
        else:
            await _clear_login_state(user_id)
            return {
                "action": "login_failed",
                "text": _t("2fa_failed", lang),
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


async def _escalate_to_browser_connect(
    user_id: str,
    state: dict,
    session_data: dict,
) -> dict[str, Any]:
    """Transfer an active login browser to browser-connect for CAPTCHA solving.

    Instead of closing the browser, we hand it off to remote_browser_connect
    so the user can solve the CAPTCHA in the browser-connect UI.
    """
    lang = state.get("language", "en")
    try:
        from src.core.config import settings
        from src.tools import remote_browser_connect

        token = secrets.token_urlsafe(24)

        # Store token metadata in Redis for browser-connect
        payload = {
            "user_id": user_id,
            "family_id": state.get("family_id", ""),
            "provider": state.get("site", ""),
        }
        await redis.set(
            f"browser_connect:{token}",
            json.dumps(payload),
            ex=remote_browser_connect.CONNECT_TTL_S,
        )

        # Create a RemoteBrowserSession from the existing Playwright objects
        session = remote_browser_connect.RemoteBrowserSession(
            token=token,
            user_id=user_id,
            family_id=state.get("family_id", ""),
            provider=state.get("site", ""),
            playwright=session_data["pw"],
            browser=session_data["browser"],
            context=session_data["context"],
            page=session_data["page"],
            created_at=time.time(),
            updated_at=time.time(),
        )
        remote_browser_connect._active_sessions[token] = session

        # Remove from our active sessions WITHOUT closing the browser
        _active_sessions.pop(user_id, None)
        await redis.delete(f"{_REDIS_PREFIX}:{user_id}")

        base_url = settings.public_base_url or ""
        connect_url = f"{base_url}/api/browser-connect/{token}"

        return {
            "action": "captcha",
            "text": _t("captcha_detected", lang),
            "connect_url": connect_url,
            "btn_text": _t("btn_solve_captcha", lang),
        }
    except Exception as e:
        logger.error("Failed to escalate to browser-connect: %s", e)
        await _clear_login_state(user_id)
        return {
            "action": "login_failed",
            "text": _t("login_failed", lang),
        }


async def _analyze_login_result(screenshot: bytes) -> str:
    """Analyze a screenshot to determine login outcome.

    Uses Gemini Flash to classify: 'success', '2fa', 'failed', 'captcha'.
    Falls back to 'failed' if analysis fails.
    """
    try:
        from google.genai import types

        from src.core.llm.clients import google_client

        client = google_client()

        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/png",
                                data=screenshot,
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
