"""Tests for browser login flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.browser_login import cancel_login, get_login_state, handle_step


async def test_get_login_state_no_flow():
    with patch("src.tools.browser_login.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await get_login_state("user-123")
    assert result is None


async def test_get_login_state_active_flow():
    import json

    state = {"step": "awaiting_email", "site": "booking.com"}
    with patch("src.tools.browser_login.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=json.dumps(state))
        result = await get_login_state("user-123")
    assert result == state
    assert result["step"] == "awaiting_email"


async def test_handle_step_no_flow():
    with patch("src.tools.browser_login.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await handle_step(
            user_id="user-123",
            family_id="family-123",
            message_text="test@email.com",
        )
    assert result["action"] == "no_flow"


async def test_handle_step_email_step():
    import json

    state = {
        "step": "awaiting_email",
        "site": "booking.com",
        "family_id": "family-123",
        "task": "check booking",
        "login_url": "https://booking.com",
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

    # Mock the next button click
    mock_submit_el = AsyncMock()
    mock_submit_el.is_visible = AsyncMock(return_value=True)
    mock_submit_el.click = AsyncMock()

    from src.tools import browser_login

    browser_login._active_sessions["user-123"] = {
        "page": mock_page,
        "browser": AsyncMock(),
        "context": AsyncMock(),
        "pw": AsyncMock(),
    }

    try:
        with (
            patch("src.tools.browser_login.redis") as mock_redis,
            patch(
                "src.tools.browser_login._detect_next_step",
                new_callable=AsyncMock,
                return_value="password",
            ),
        ):
            mock_redis.get = AsyncMock(return_value=json.dumps(state))
            mock_redis.set = AsyncMock()

            result = await handle_step(
                user_id="user-123",
                family_id="family-123",
                message_text="user@example.com",
            )
        assert result["action"] == "ask_password"
        assert "password" in result["text"].lower()
    finally:
        browser_login._active_sessions.pop("user-123", None)


async def test_handle_step_uber_phone_goes_to_2fa():
    """Uber phone entry should go to 2FA (OTP), not password."""
    import json

    state = {
        "step": "awaiting_email",
        "site": "uber.com",
        "family_id": "family-123",
        "task": "order uber",
        "login_url": "https://auth.uber.com/login",
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

    from src.tools import browser_login

    browser_login._active_sessions["user-123"] = {
        "page": mock_page,
        "browser": AsyncMock(),
        "context": AsyncMock(),
        "pw": AsyncMock(),
    }

    try:
        with (
            patch("src.tools.browser_login.redis") as mock_redis,
            patch(
                "src.tools.browser_login._detect_next_step",
                new_callable=AsyncMock,
                return_value="2fa",
            ),
        ):
            mock_redis.get = AsyncMock(return_value=json.dumps(state))
            mock_redis.set = AsyncMock()

            result = await handle_step(
                user_id="user-123",
                family_id="family-123",
                message_text="+1234567890",
            )
        assert result["action"] == "ask_2fa"
        assert "code" in result["text"].lower() or "код" in result["text"].lower()
    finally:
        browser_login._active_sessions.pop("user-123", None)


async def test_handle_step_password_deletes_message():
    """Verify password message is deleted from Telegram for security."""
    import json

    state = {
        "step": "awaiting_password",
        "site": "booking.com",
        "family_id": "family-123",
        "task": "check booking",
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

    from src.tools import browser_login

    browser_login._active_sessions["user-123"] = {
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

            await handle_step(
                user_id="user-123",
                family_id="family-123",
                message_text="mysecretpass",
                gateway=mock_gateway,
                chat_id="chat-123",
                message_id="msg-456",
            )

        # Password message should be deleted
        mock_gateway.delete_message.assert_called_once_with("chat-123", "msg-456")
    finally:
        browser_login._active_sessions.pop("user-123", None)


async def test_cancel_login():
    with (
        patch("src.tools.browser_login.redis") as mock_redis,
        patch("src.tools.browser_login._cleanup_browser", new_callable=AsyncMock),
    ):
        mock_redis.delete = AsyncMock()
        await cancel_login("user-123")
        mock_redis.delete.assert_called_once()


async def test_analyze_login_result_success():
    from src.tools.browser_login import _analyze_login_result

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "success"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("src.core.llm.clients.google_client", return_value=mock_client):
        result = await _analyze_login_result(b"fake_screenshot")
    assert result == "success"


async def test_analyze_login_result_fallback():
    from src.tools.browser_login import _analyze_login_result

    with patch(
        "src.core.llm.clients.google_client", side_effect=Exception("no client")
    ):
        result = await _analyze_login_result(b"fake_screenshot")
    assert result == "failed"
