"""Tests for chat-based login flow — site configs, i18n, taxi/food integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.browser_login import (
    _SITE_LOGIN_CONFIG,
    _STRINGS,
    _get_site_config,
    _t,
    start_login,
)

# ---------------------------------------------------------------------------
# Site config tests
# ---------------------------------------------------------------------------


def test_uber_site_config_uses_phone():
    config = _get_site_config("uber.com")
    assert config["credential_type"] == "phone"
    assert config["skip_password"] is True
    assert any("phone" in s.lower() for s in config.get("input_selectors", []))


def test_ubereats_site_config_uses_phone():
    config = _get_site_config("ubereats.com")
    assert config["credential_type"] == "phone"


def test_doordash_site_config_uses_email():
    config = _get_site_config("doordash.com")
    assert config["credential_type"] == "email"


def test_unknown_site_defaults_to_email():
    config = _get_site_config("randomsite.com")
    # Unknown sites return empty dict — callers use .get("credential_type", "email")
    assert config.get("credential_type", "email") == "email"


def test_uber_skip_password_flag():
    """Uber/UberEats should have skip_password=True."""
    assert _get_site_config("uber.com").get("skip_password") is True
    assert _get_site_config("ubereats.com").get("skip_password") is True


def test_doordash_no_skip_password():
    """DoorDash uses standard email/password flow."""
    assert not _get_site_config("doordash.com").get("skip_password")


def test_site_config_keys():
    """All configured sites must have credential_type."""
    for domain, cfg in _SITE_LOGIN_CONFIG.items():
        assert "credential_type" in cfg, f"{domain} missing credential_type"
        assert cfg["credential_type"] in ("phone", "email")


# ---------------------------------------------------------------------------
# _detect_next_step tests
# ---------------------------------------------------------------------------


async def test_detect_next_step_otp_field_for_skip_password():
    """skip_password site with OTP input visible → returns '2fa'."""
    from src.tools.browser_login import _detect_next_step

    mock_page = AsyncMock()
    mock_el = AsyncMock()
    mock_el.is_visible = AsyncMock(return_value=True)
    mock_locator = MagicMock()
    mock_locator.first = mock_el
    mock_page.locator = MagicMock(return_value=mock_locator)

    result = await _detect_next_step(mock_page, {"skip_password": True})
    assert result == "2fa"


async def test_detect_next_step_password_field():
    """Password input visible → returns 'password'."""
    from src.tools.browser_login import _detect_next_step

    mock_page = AsyncMock()

    call_count = 0

    def mock_locator_side_effect(selector):
        nonlocal call_count
        mock_el = AsyncMock()
        # OTP selectors return not visible, password selectors return visible
        is_password = 'password' in selector.lower()
        mock_el.is_visible = AsyncMock(return_value=is_password)
        mock_loc = MagicMock()
        mock_loc.first = mock_el
        return mock_loc

    mock_page.locator = MagicMock(side_effect=mock_locator_side_effect)

    result = await _detect_next_step(mock_page, {})
    assert result == "password"


async def test_detect_next_step_falls_back_to_gemini():
    """No DOM selectors match → falls back to Gemini analysis."""
    from src.tools.browser_login import _detect_next_step

    mock_page = AsyncMock()
    mock_el = AsyncMock()
    mock_el.is_visible = AsyncMock(return_value=False)
    mock_locator = MagicMock()
    mock_locator.first = mock_el
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.screenshot = AsyncMock(return_value=b"screenshot")

    with patch(
        "src.tools.browser_login._analyze_post_credential_page",
        new_callable=AsyncMock,
        return_value="2fa",
    ):
        result = await _detect_next_step(mock_page, {})
    assert result == "2fa"


# ---------------------------------------------------------------------------
# i18n tests
# ---------------------------------------------------------------------------


def test_i18n_all_languages_have_same_keys():
    en_keys = set(_STRINGS["en"].keys())
    for lang in ("ru", "es"):
        lang_keys = set(_STRINGS[lang].keys())
        assert lang_keys == en_keys, f"{lang} missing: {en_keys - lang_keys}"


def test_i18n_prompts_ru():
    text = _t("ask_phone", "ru")
    assert text  # Non-empty
    assert "телефон" in text.lower() or "номер" in text.lower()


def test_i18n_prompts_es():
    text = _t("ask_phone", "es")
    assert text
    assert "teléfono" in text.lower() or "número" in text.lower()


def test_i18n_fallback_to_en():
    text = _t("ask_email", "fr")  # French not supported
    en_text = _t("ask_email", "en")
    assert text == en_text


# ---------------------------------------------------------------------------
# start_login tests
# ---------------------------------------------------------------------------


def _mock_playwright():
    """Create a mock Playwright setup that returns a page, context, browser, pw."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"screenshot")

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw.__aexit__ = AsyncMock(return_value=None)

    return mock_pw


async def test_start_login_uber_asks_phone():
    """Uber login should ask for phone number, not email."""
    mock_pw = _mock_playwright()

    with (
        patch("src.tools.browser_login.redis") as mock_redis,
        patch(
            "src.tools.browser_login.browser_service.extract_domain",
            return_value="uber.com",
        ),
        patch(
            "src.tools.browser_login.browser_service.get_login_url",
            return_value="https://auth.uber.com/login",
        ),
        patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ),
    ):
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await start_login(
            user_id="user-1",
            family_id="fam-1",
            site="uber.com",
            task="order uber",
            language="en",
        )

    assert result["action"] == "ask_phone"
    assert "phone" in result["text"].lower()


async def test_start_login_doordash_asks_email():
    """DoorDash login should ask for email."""
    mock_pw = _mock_playwright()

    with (
        patch("src.tools.browser_login.redis") as mock_redis,
        patch(
            "src.tools.browser_login.browser_service.extract_domain",
            return_value="doordash.com",
        ),
        patch(
            "src.tools.browser_login.browser_service.get_login_url",
            return_value="https://identity.doordash.com/auth",
        ),
        patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ),
    ):
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await start_login(
            user_id="user-1",
            family_id="fam-1",
            site="doordash.com",
            task="order food",
            language="en",
        )

    assert result["action"] == "ask_email"
    assert "email" in result["text"].lower()


async def test_start_login_default_asks_email():
    """Unknown site should default to email prompt."""
    mock_pw = _mock_playwright()

    with (
        patch("src.tools.browser_login.redis") as mock_redis,
        patch(
            "src.tools.browser_login.browser_service.extract_domain",
            return_value="unknown.com",
        ),
        patch(
            "src.tools.browser_login.browser_service.get_login_url",
            return_value="https://unknown.com/login",
        ),
        patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ),
    ):
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await start_login(
            user_id="user-1",
            family_id="fam-1",
            site="unknown.com",
            task="browse",
            language="en",
        )

    assert result["action"] == "ask_email"


# ---------------------------------------------------------------------------
# Taxi / food flow integration tests
# ---------------------------------------------------------------------------


async def test_taxi_build_login_prompt_calls_chat_login():
    """Taxi _build_login_prompt should call browser_login.start_login, not connect URL."""
    from src.tools import taxi_booking

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "provider": "uber.com",
        "language": "en",
        "step": "awaiting_login",
    }

    mock_login_result = {
        "action": "ask_phone",
        "text": "Enter your phone number for Uber:",
        "screenshot_bytes": b"screenshot",
    }
    with (
        patch("src.tools.taxi_booking.redis") as mock_redis,
        patch(
            "src.tools.browser_login.start_login",
            new_callable=AsyncMock,
            return_value=mock_login_result,
        ) as mock_start,
    ):
        mock_redis.set = AsyncMock()
        result = await taxi_booking._build_login_prompt(state)

    mock_start.assert_called_once()
    assert result["action"] == "need_login"
    assert "phone" in result["text"].lower()
    assert result.get("photo_bytes") == b"screenshot"
    # State should be updated to awaiting_chat_login
    assert state["step"] == "awaiting_chat_login"


async def test_taxi_awaiting_chat_login_cancel():
    """Cancel during awaiting_chat_login should cancel the flow."""
    from src.tools import taxi_booking

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "provider": "uber.com",
        "language": "en",
        "step": "awaiting_chat_login",
    }
    with patch("src.tools.taxi_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.delete = AsyncMock()
        result = await taxi_booking.handle_text_input("user-1", "отмена")
    assert result is not None
    assert result["action"] == "cancelled"


async def test_taxi_awaiting_chat_login_passthrough():
    """Non-cancel input during awaiting_chat_login should return None (for router)."""
    from src.tools import taxi_booking

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "provider": "uber.com",
        "language": "en",
        "step": "awaiting_chat_login",
    }
    with patch("src.tools.taxi_booking.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        result = await taxi_booking.handle_text_input("user-1", "+1234567890")
    assert result is None


async def test_food_awaiting_chat_login_cancel():
    """Cancel during food awaiting_chat_login should cancel the flow."""
    from src.tools import food_ordering

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "platform": "ubereats.com",
        "language": "ru",
        "step": "awaiting_chat_login",
    }
    with patch("src.tools.food_ordering.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.delete = AsyncMock()
        result = await food_ordering.handle_text_input("user-1", "cancel")
    assert result is not None
    assert result["action"] == "cancelled"


async def test_food_awaiting_chat_login_passthrough():
    """Non-cancel input during food awaiting_chat_login returns None."""
    from src.tools import food_ordering

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "platform": "ubereats.com",
        "language": "en",
        "step": "awaiting_chat_login",
    }
    with patch("src.tools.food_ordering.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        result = await food_ordering.handle_text_input("user-1", "user@email.com")
    assert result is None


async def test_taxi_login_ready_accepts_chat_login_step():
    """handle_login_ready should work when step is awaiting_chat_login."""
    from src.tools import taxi_booking

    state = {
        "flow_id": "abc123",
        "user_id": "user-1",
        "family_id": "fam-1",
        "provider": "uber.com",
        "language": "en",
        "step": "awaiting_chat_login",
        "destination": "airport",
    }
    with (
        patch("src.tools.taxi_booking.redis") as mock_redis,
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.browser_login.start_login",
            new_callable=AsyncMock,
            return_value={"action": "ask_phone", "text": "Enter phone:"},
        ),
    ):
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        mock_redis.set = AsyncMock()
        result = await taxi_booking.handle_login_ready("user-1")

    # Should not return "no_flow" — should accept awaiting_chat_login
    assert result["action"] != "no_flow"


# ---------------------------------------------------------------------------
# Password message deletion tests
# ---------------------------------------------------------------------------


async def test_password_message_deleted_from_chat():
    """Password message should be deleted from Telegram for security."""
    from src.tools import browser_login

    state = {
        "step": "awaiting_password",
        "site": "booking.com",
        "family_id": "fam-1",
        "task": "check booking",
        "language": "en",
    }

    mock_page = AsyncMock()
    mock_el = AsyncMock()
    mock_el.is_visible = AsyncMock(return_value=True)
    mock_el.fill = AsyncMock()
    mock_locator = MagicMock()
    mock_locator.first = mock_el
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.screenshot = AsyncMock(return_value=b"screenshot")
    mock_page.keyboard = AsyncMock()

    mock_context = AsyncMock()
    mock_context.storage_state = AsyncMock(return_value={"cookies": []})

    mock_gateway = AsyncMock()
    mock_gateway.delete_message = AsyncMock()

    browser_login._active_sessions["user-1"] = {
        "page": mock_page,
        "browser": AsyncMock(),
        "context": mock_context,
        "pw": AsyncMock(),
    }

    try:
        with (
            patch("src.tools.browser_login.redis") as mock_redis,
            patch(
                "src.tools.browser_login._analyze_login_result",
                new_callable=AsyncMock,
                return_value="failed",
            ),
        ):
            mock_redis.get = AsyncMock(return_value=json.dumps(state))
            mock_redis.set = AsyncMock()
            mock_redis.delete = AsyncMock()

            await browser_login.handle_step(
                user_id="user-1",
                family_id="fam-1",
                message_text="mysecretpass",
                gateway=mock_gateway,
                chat_id="chat-1",
                message_id="msg-1",
            )

        mock_gateway.delete_message.assert_called_once_with("chat-1", "msg-1")
    finally:
        browser_login._active_sessions.pop("user-1", None)


# ---------------------------------------------------------------------------
# CAPTCHA escalation tests
# ---------------------------------------------------------------------------


async def test_captcha_escalates_to_browser_connect():
    """CAPTCHA detection should transfer session to browser-connect."""
    from src.tools.browser_login import _escalate_to_browser_connect

    state = {
        "site": "uber.com",
        "family_id": "fam-1",
        "language": "en",
    }
    session_data = {
        "pw": MagicMock(),
        "browser": AsyncMock(),
        "context": AsyncMock(),
        "page": AsyncMock(),
    }

    with (
        patch("src.tools.browser_login.redis") as mock_redis,
        patch(
            "src.tools.browser_login.remote_browser_connect",
            create=True,
        ) as mock_rbc,
        patch("src.core.config.settings") as mock_settings,
    ):
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_rbc.CONNECT_TTL_S = 600
        mock_rbc._active_sessions = {}
        mock_rbc.RemoteBrowserSession = MagicMock()
        mock_settings.public_base_url = "https://example.com"

        result = await _escalate_to_browser_connect("user-1", state, session_data)

    assert result["action"] == "captcha"
    assert "connect_url" in result
    assert "example.com" in result["connect_url"]


# ---------------------------------------------------------------------------
# Router-level login flow resumption tests
# ---------------------------------------------------------------------------


async def test_login_success_resumes_taxi_flow():
    """After login success, router should resume pending taxi flow."""
    from src.core.router import _check_browser_login_flow
    from src.gateway.types import IncomingMessage, MessageType

    msg = IncomingMessage(
        id="msg-1", user_id="user-1", chat_id="chat-1",
        type=MessageType.text, text="mysecretpass",
    )
    ctx = MagicMock()
    ctx.user_id = "user-1"
    ctx.family_id = "fam-1"
    ctx.channel = "telegram"

    taxi_state = {"step": "awaiting_chat_login", "flow_id": "abc123"}

    with (
        patch(
            "src.tools.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value={"step": "awaiting_password"},
        ),
        patch(
            "src.tools.browser_login.handle_step",
            new_callable=AsyncMock,
            return_value={
                "action": "login_success",
                "text": "Login successful!",
                "task": "taxi",
                "site": "uber.com",
            },
        ),
        patch("src.gateway.factory.get_gateway", return_value=MagicMock()),
        patch(
            "src.tools.taxi_booking.get_taxi_state",
            new_callable=AsyncMock,
            return_value=taxi_state,
        ),
        patch(
            "src.tools.taxi_booking.handle_login_ready",
            new_callable=AsyncMock,
            return_value={
                "text": "Searching for rides...",
                "buttons": [{"text": "UberX", "callback": "taxi_select:abc:0"}],
            },
        ) as mock_resume,
    ):
        result = await _check_browser_login_flow(msg, ctx)

    mock_resume.assert_called_once_with("user-1")
    assert result is not None
    assert "Login successful!" in result.text
    assert "rides" in result.text.lower()
    assert result.buttons is not None


async def test_login_success_resumes_food_flow():
    """After login success, router should resume pending food flow."""
    from src.core.router import _check_browser_login_flow
    from src.gateway.types import IncomingMessage, MessageType

    msg = IncomingMessage(
        id="msg-1", user_id="user-1", chat_id="chat-1",
        type=MessageType.text, text="mysecretpass",
    )
    ctx = MagicMock()
    ctx.user_id = "user-1"
    ctx.family_id = "fam-1"
    ctx.channel = "telegram"

    food_state = {"step": "awaiting_chat_login", "flow_id": "food123"}

    with (
        patch(
            "src.tools.browser_login.get_login_state",
            new_callable=AsyncMock,
            return_value={"step": "awaiting_password"},
        ),
        patch(
            "src.tools.browser_login.handle_step",
            new_callable=AsyncMock,
            return_value={
                "action": "login_success",
                "text": "Login successful!",
                "task": "food",
                "site": "ubereats.com",
            },
        ),
        patch("src.gateway.factory.get_gateway", return_value=MagicMock()),
        patch(
            "src.tools.taxi_booking.get_taxi_state",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.tools.food_ordering.get_food_state",
            new_callable=AsyncMock,
            return_value=food_state,
        ),
        patch(
            "src.tools.food_ordering.handle_login_ready",
            new_callable=AsyncMock,
            return_value={
                "text": "Searching for restaurants...",
                "buttons": [{"text": "McDonald's", "callback": "food_select:f1:0"}],
            },
        ) as mock_resume,
    ):
        result = await _check_browser_login_flow(msg, ctx)

    mock_resume.assert_called_once_with("user-1")
    assert result is not None
    assert "Login successful!" in result.text
    assert "restaurants" in result.text.lower()
    assert result.buttons is not None
