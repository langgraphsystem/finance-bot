"""Tests for browser session service."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.browser_service import extract_domain

_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_TEST_FAMILY_ID = "00000000-0000-0000-0000-000000000002"


def test_extract_domain_full_url():
    assert extract_domain("https://www.booking.com/hotels?q=NYC") == "booking.com"


def test_extract_domain_with_www():
    assert extract_domain("www.amazon.co.uk") == "amazon.co.uk"


def test_extract_domain_bare():
    assert extract_domain("booking.com") == "booking.com"


def test_extract_domain_with_path():
    assert extract_domain("https://airbnb.com/rooms/12345") == "airbnb.com"


def test_extract_domain_uppercase():
    assert extract_domain("HTTPS://WWW.GOOGLE.COM/search") == "google.com"


def test_extract_domain_with_port():
    assert extract_domain("http://localhost:8080/api") == "localhost:8080"


async def test_get_storage_state_not_found():
    from src.tools.browser_service import get_storage_state

    with patch("src.tools.browser_service.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_storage_state(_TEST_USER_ID, "booking.com")
    assert result is None


async def test_encrypt_decrypt_round_trip():
    """Test that encrypt → decrypt returns original data."""
    from cryptography.fernet import Fernet

    # Set a test encryption key
    test_key = Fernet.generate_key().decode()
    with patch.dict(os.environ, {"OAUTH_ENCRYPTION_KEY": test_key}):
        # Reset cached fernet
        import src.core.crypto

        src.core.crypto._fernet = None

        from src.core.crypto import decrypt_token, encrypt_token

        test_state = {"cookies": [{"name": "session", "value": "abc123"}]}
        plaintext = json.dumps(test_state)

        encrypted = encrypt_token(plaintext)
        decrypted = decrypt_token(encrypted)

        assert json.loads(decrypted) == test_state

        # Cleanup
        src.core.crypto._fernet = None


async def test_delete_session():
    from src.tools.browser_service import delete_session

    with patch("src.tools.browser_service.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        result = await delete_session(_TEST_USER_ID, "booking.com")
    assert result is True


async def test_delete_session_not_found():
    from src.tools.browser_service import delete_session

    with patch("src.tools.browser_service.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        result = await delete_session(_TEST_USER_ID, "nonexistent.com")
    assert result is False


async def test_log_action():
    from src.tools.browser_service import log_action

    with patch("src.tools.browser_service.async_session") as mock_session_maker:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        await log_action(
            user_id=_TEST_USER_ID,
            action_type="login_success",
            url="https://booking.com",
            details={"task": "check booking"},
        )
        mock_session.add.assert_called_once()


async def test_execute_with_session_prefers_computer_use_backend():
    from src.tools import browser_service

    with (
        patch.object(browser_service.settings, "ff_browser_computer_use", True),
        patch.object(browser_service.settings, "openai_api_key", "sk-test"),
        patch(
            "src.tools.browser_service.get_storage_state",
            new_callable=AsyncMock,
            return_value={"cookies": [{"name": "session", "value": "abc"}]},
        ),
        patch(
            "src.tools.browser_service.save_storage_state",
            new_callable=AsyncMock,
        ) as mock_save,
        patch(
            "src.tools.browser_service.log_action",
            new_callable=AsyncMock,
        ) as mock_log,
        patch(
            "src.tools.computer_use_service.execute_task",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": "Order placed successfully.",
                "engine": "openai_computer_use",
                "storage_state": {"cookies": [{"name": "session", "value": "new"}]},
                "url": "https://amazon.com/checkout/complete",
            },
        ) as mock_cu,
    ):
        result = await browser_service.execute_with_session(
            user_id=_TEST_USER_ID,
            family_id=_TEST_FAMILY_ID,
            site="amazon.com",
            task="Buy paper towels from my saved cart",
        )

    assert result["success"] is True
    assert result["engine"] == "openai_computer_use"
    mock_cu.assert_awaited_once()
    mock_save.assert_awaited_once()
    mock_log.assert_awaited_once()
