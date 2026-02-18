"""Tests for Google OAuth token management."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.google_auth import (
    has_google_connection,
    parse_email_headers,
    require_google_or_prompt,
)


@pytest.mark.asyncio
async def test_has_connection_true():
    """Returns True when user has OAuth token."""
    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=uuid.uuid4())
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.google_auth.async_session", return_value=mock_session):
        result = await has_google_connection(str(uuid.uuid4()))

    assert result is True


@pytest.mark.asyncio
async def test_has_connection_false():
    """Returns False when user has no OAuth token."""
    mock_session = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.google_auth.async_session", return_value=mock_session):
        result = await has_google_connection(str(uuid.uuid4()))

    assert result is False


@pytest.mark.asyncio
async def test_has_connection_exception():
    """Returns False on DB exception."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.google_auth.async_session", return_value=mock_session):
        result = await has_google_connection(str(uuid.uuid4()))

    assert result is False


@pytest.mark.asyncio
async def test_require_google_returns_none_when_connected():
    """Returns None when user is connected — caller proceeds."""
    with patch(
        "src.core.google_auth.has_google_connection",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await require_google_or_prompt(str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_require_google_returns_prompt_when_not_connected():
    """Returns SkillResult with connect button when not connected."""
    with (
        patch(
            "src.core.google_auth.has_google_connection",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("api.oauth.redis", new_callable=AsyncMock),
        patch(
            "api.oauth.settings",
            MagicMock(google_redirect_uri="https://app.com/oauth/google/callback"),
        ),
    ):
        result = await require_google_or_prompt(str(uuid.uuid4()))

    assert result is not None
    assert "Подключить Google" in (result.buttons[0]["text"] if result.buttons else "")
    assert "подключить" in result.response_text.lower()


def test_parse_email_headers_basic():
    """Extracts from/subject/snippet from Gmail message."""
    msg = {
        "id": "msg123",
        "threadId": "thread456",
        "snippet": "Hello, this is a test...",
        "payload": {
            "headers": [
                {"name": "From", "value": "John <john@example.com>"},
                {"name": "Subject", "value": "Meeting tomorrow"},
                {"name": "Date", "value": "Mon, 17 Feb 2026 10:00:00 -0500"},
            ]
        },
    }
    result = parse_email_headers(msg)
    assert result["id"] == "msg123"
    assert result["thread_id"] == "thread456"
    assert result["from"] == "John <john@example.com>"
    assert result["subject"] == "Meeting tomorrow"
    assert result["snippet"] == "Hello, this is a test..."


def test_parse_email_headers_missing():
    """Returns defaults when headers are missing."""
    msg = {"id": "msg1", "threadId": "t1", "payload": {"headers": []}}
    result = parse_email_headers(msg)
    assert result["from"] == ""
    assert result["subject"] == "(без темы)"
    assert result["snippet"] == ""
