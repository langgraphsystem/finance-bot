"""Tests for action approval system."""

import json
from unittest.mock import AsyncMock, patch

from src.core.approval import APPROVAL_TTL_S, ApprovalManager, approval_manager


def test_approval_manager_singleton():
    assert approval_manager is not None
    assert isinstance(approval_manager, ApprovalManager)


def test_approval_ttl():
    assert APPROVAL_TTL_S == 600


async def test_request_approval_returns_buttons():
    mock_redis = AsyncMock()

    with patch("src.core.approval.redis", mock_redis):
        result = await approval_manager.request_approval(
            user_id="user-1",
            action="web_action",
            data={"task": "fill form"},
            summary="I'll fill the form for you",
        )

    assert "Confirm this action?" in result.response_text
    assert len(result.buttons) == 2
    assert result.buttons[0]["text"] == "Confirm"
    assert result.buttons[1]["text"] == "Cancel"
    assert "confirm_action:" in result.buttons[0]["callback"]
    assert "cancel_action:" in result.buttons[1]["callback"]

    # Verify Redis was called with correct TTL
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    assert call_args[0][1] == APPROVAL_TTL_S


async def test_get_pending_returns_data():
    payload = json.dumps({"action": "web_action", "data": {}, "user_id": "u1"})
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=payload)

    with patch("src.core.approval.redis", mock_redis):
        result = await approval_manager.get_pending("abc123")

    assert result is not None
    assert result["action"] == "web_action"


async def test_get_pending_returns_none_for_expired():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("src.core.approval.redis", mock_redis):
        result = await approval_manager.get_pending("expired-id")

    assert result is None


async def test_consume_retrieves_and_deletes():
    payload = json.dumps({"action": "send_email", "data": {}, "user_id": "u1"})
    mock_redis = AsyncMock()
    mock_redis.getdel = AsyncMock(return_value=payload)

    with patch("src.core.approval.redis", mock_redis):
        result = await approval_manager.consume("abc123")

    assert result is not None
    assert result["action"] == "send_email"
    mock_redis.getdel.assert_called_once_with("approval:abc123")


async def test_handle_rejection_deletes_and_returns_message():
    mock_redis = AsyncMock()

    with patch("src.core.approval.redis", mock_redis):
        result = await approval_manager.handle_rejection("abc123")

    assert "cancelled" in result.response_text.lower()
    mock_redis.delete.assert_called_once_with("approval:abc123")
