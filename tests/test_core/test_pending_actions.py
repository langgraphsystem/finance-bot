"""Tests for pending action helpers."""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_store_pending_action():
    """Store returns a short pending_id and writes to Redis."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    with patch("src.core.pending_actions.redis", mock_redis):
        from src.core.pending_actions import store_pending_action

        pid = await store_pending_action(
            "send_email", "u1", "f1", {"email_to": "a@b.com"}
        )

    assert len(pid) == 8
    mock_redis.set.assert_called_once()

    # Verify the stored payload
    call_args = mock_redis.set.call_args
    key = call_args[0][0]
    payload = json.loads(call_args[0][1])
    assert key == f"pending_action:{pid}"
    assert payload["intent"] == "send_email"
    assert payload["user_id"] == "u1"
    assert payload["action_data"]["email_to"] == "a@b.com"
    assert call_args[1]["ex"] == 600


@pytest.mark.asyncio
async def test_get_pending_action_found():
    """get_pending_action returns parsed dict when found."""
    data = json.dumps(
        {
            "intent": "create_event",
            "user_id": "u1",
            "family_id": "f1",
            "action_data": {"title": "Meeting"},
        }
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=data)

    with patch("src.core.pending_actions.redis", mock_redis):
        from src.core.pending_actions import get_pending_action

        result = await get_pending_action("abc12345")

    assert result is not None
    assert result["intent"] == "create_event"
    assert result["action_data"]["title"] == "Meeting"


@pytest.mark.asyncio
async def test_get_pending_action_expired():
    """get_pending_action returns None when key expired."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("src.core.pending_actions.redis", mock_redis):
        from src.core.pending_actions import get_pending_action

        result = await get_pending_action("expired_id")

    assert result is None


@pytest.mark.asyncio
async def test_delete_pending_action():
    """delete_pending_action removes the key from Redis."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    with patch("src.core.pending_actions.redis", mock_redis):
        from src.core.pending_actions import delete_pending_action

        await delete_pending_action("abc12345")

    mock_redis.delete.assert_called_once_with("pending_action:abc12345")
