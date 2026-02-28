"""Tests for undo window — time-limited undo after quick actions."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.core.undo import (
    UNDO_INTENTS,
    UNDO_TTL,
    execute_undo,
    pop_undo,
    store_undo,
)

# --- Constants ---


def test_undo_ttl():
    assert UNDO_TTL == 120


def test_undo_intents_contains_expected():
    expected = {"add_expense", "add_income", "create_task", "track_food", "track_drink"}
    assert expected == UNDO_INTENTS


# --- store / pop ---


@pytest.fixture
def mock_redis():
    with patch("src.core.undo.redis") as mock:
        mock.set = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock()
        yield mock


async def test_store_undo(mock_redis):
    await store_undo("user1", "add_expense", "abc-123", "transactions")
    mock_redis.set.assert_called_once()
    key, payload = mock_redis.set.call_args.args[:2]
    assert key == "undo:user1"
    data = json.loads(payload)
    assert data["intent"] == "add_expense"
    assert data["record_id"] == "abc-123"
    assert data["table"] == "transactions"
    assert mock_redis.set.call_args.kwargs.get("ex") == UNDO_TTL


async def test_pop_undo_found(mock_redis):
    payload = {"intent": "add_expense", "record_id": "abc-123", "table": "transactions"}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))
    result = await pop_undo("user1")
    assert result["record_id"] == "abc-123"
    mock_redis.delete.assert_called_once_with("undo:user1")


async def test_pop_undo_expired(mock_redis):
    result = await pop_undo("user1")
    assert result is None
    mock_redis.delete.assert_not_called()


# --- execute_undo ---


async def test_execute_undo_expired(mock_redis):
    result = await execute_undo("user1", "family1")
    assert "expired" in result.lower() or "nothing" in result.lower()


async def test_execute_undo_success(mock_redis):
    record_uuid = "12345678-1234-5678-1234-567812345678"
    family_uuid = "abcdefab-cdef-abcd-efab-cdefabcdefab"
    payload = {"intent": "add_expense", "record_id": record_uuid, "table": "transactions"}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.undo.async_session", return_value=mock_session):
        result = await execute_undo("user1", family_uuid)
    assert "undone" in result.lower()
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


async def test_execute_undo_unknown_table(mock_redis):
    payload = {"intent": "add_expense", "record_id": "abc-123", "table": "unknown_table"}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))
    result = await execute_undo("user1", "family1")
    assert "failed" in result.lower() or "unknown" in result.lower()


async def test_execute_undo_db_error(mock_redis):
    record_uuid = "12345678-1234-5678-1234-567812345678"
    family_uuid = "abcdefab-cdef-abcd-efab-cdefabcdefab"
    payload = {"intent": "add_expense", "record_id": record_uuid, "table": "transactions"}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(side_effect=Exception("DB error"))

    with patch("src.core.undo.async_session", return_value=mock_session):
        result = await execute_undo("user1", family_uuid)
    assert "failed" in result.lower()
