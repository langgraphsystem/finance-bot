"""Tests for Telegram WebApp HMAC-SHA256 authentication."""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, urlencode

import pytest
from fastapi import HTTPException

from api.webapp_auth import validate_webapp_data

BOT_TOKEN = "test_token"


def _build_init_data(
    user: dict,
    auth_date: int | None = None,
    bot_token: str = BOT_TOKEN,
    tamper_hash: str | None = None,
    omit_hash: bool = False,
    omit_user: bool = False,
) -> str:
    """Build a valid Telegram WebApp initData query string.

    Follows the official Telegram algorithm:
    1. Collect key=value pairs (excluding hash)
    2. Sort alphabetically by key
    3. Join with newline -> data_check_string
    4. secret_key = HMAC-SHA256("WebAppData", bot_token)
    5. hash = HMAC-SHA256(secret_key, data_check_string)
    """
    if auth_date is None:
        auth_date = int(time.time())

    params: dict[str, str] = {"auth_date": str(auth_date)}
    if not omit_user:
        params["user"] = json.dumps(user)

    # Build data-check-string
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )

    # Calculate HMAC
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not omit_hash:
        params["hash"] = tamper_hash if tamper_hash else calculated_hash

    return urlencode(params)


def _make_request(init_data: str):
    """Create a mock FastAPI Request with the given init data header."""
    request = AsyncMock()
    request.headers = {"X-Telegram-Init-Data": init_data}
    return request


@pytest.mark.asyncio
async def test_valid_init_data_passes():
    """Valid HMAC-signed init data should return user dict."""
    user = {"id": 123456, "first_name": "Test", "username": "testuser"}
    init_data = _build_init_data(user)
    request = _make_request(init_data)

    result = await validate_webapp_data(request)

    assert result["id"] == 123456
    assert result["first_name"] == "Test"
    assert result["username"] == "testuser"


@pytest.mark.asyncio
async def test_missing_header_fails():
    """Request without X-Telegram-Init-Data header should fail with 401."""
    request = AsyncMock()
    request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "Missing Telegram init data" in exc_info.value.detail


@pytest.mark.asyncio
async def test_empty_header_fails():
    """Empty init data header should fail with 401."""
    request = _make_request("")

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_hash_fails():
    """Init data without hash parameter should fail with 401."""
    user = {"id": 123456, "first_name": "Test"}
    init_data = _build_init_data(user, omit_hash=True)
    request = _make_request(init_data)

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "Missing hash" in exc_info.value.detail


@pytest.mark.asyncio
async def test_invalid_hash_fails():
    """Tampered hash should fail with 401."""
    user = {"id": 123456, "first_name": "Test"}
    init_data = _build_init_data(user, tamper_hash="deadbeef" * 8)
    request = _make_request(init_data)

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "Invalid hash" in exc_info.value.detail


@pytest.mark.asyncio
async def test_expired_auth_date_fails():
    """Auth date older than 1 hour should fail with 401."""
    user = {"id": 123456, "first_name": "Test"}
    old_ts = int(time.time()) - 7200  # 2 hours ago
    init_data = _build_init_data(user, auth_date=old_ts)
    request = _make_request(init_data)

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail


@pytest.mark.asyncio
async def test_missing_user_data_fails():
    """Init data without user field should fail with 401."""
    user = {"id": 123456, "first_name": "Test"}
    init_data = _build_init_data(user, omit_user=True)
    request = _make_request(init_data)

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "Missing user data" in exc_info.value.detail


@pytest.mark.asyncio
async def test_wrong_bot_token_fails():
    """Init data signed with different bot token should fail."""
    user = {"id": 123456, "first_name": "Test"}
    # Sign with a different token
    init_data = _build_init_data(user, bot_token="wrong_token")
    request = _make_request(init_data)

    with pytest.raises(HTTPException) as exc_info:
        await validate_webapp_data(request)
    assert exc_info.value.status_code == 401
    assert "Invalid hash" in exc_info.value.detail
