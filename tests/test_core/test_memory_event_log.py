"""Tests for persisted versioned memory event logging."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.event_log import (
    MEMORY_TOMBSTONE_ACTION,
    MEMORY_UPSERT_ACTION,
    list_memory_history,
    record_memory_event,
)


async def test_record_memory_event_increments_version_and_merges_metadata():
    user_id = str(uuid.uuid4())
    family_id = uuid.uuid4()
    session = AsyncMock()
    session.scalar = AsyncMock(
        side_effect=[
            {
                "store": "identity",
                "slot": "identity:name",
                "version": 2,
                "value": "Maria",
                "tombstoned": False,
                "metadata": {"category": "user_identity", "source": "core_identity"},
            },
            family_id,
        ]
    )

    with patch("src.core.memory.event_log.log_action", new_callable=AsyncMock) as mock_log:
        payload = await record_memory_event(
            session,
            user_id=user_id,
            store="identity",
            slot="identity:name",
            action=MEMORY_UPSERT_ACTION,
            old_value="Maria",
            new_value="Mary",
            metadata={"field": "name"},
        )

    assert payload["version"] == 3
    assert payload["value"] == "Mary"
    assert payload["metadata"]["category"] == "user_identity"
    assert payload["metadata"]["field"] == "name"
    mock_log.assert_awaited_once()
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["action"] == MEMORY_UPSERT_ACTION
    assert call_kwargs["old_data"]["version"] == 2
    assert call_kwargs["old_data"]["value"] == "Maria"
    assert call_kwargs["new_data"]["version"] == 3
    assert call_kwargs["new_data"]["value"] == "Mary"
    assert call_kwargs["family_id"] == str(family_id)


async def test_record_memory_event_marks_tombstones():
    user_id = str(uuid.uuid4())
    family_id = uuid.uuid4()
    session = AsyncMock()
    session.scalar = AsyncMock(
        side_effect=[
            {
                "store": "rule",
                "slot": "rule:reply briefly",
                "version": 1,
                "value": "reply briefly",
                "tombstoned": False,
                "metadata": {"category": "user_rule"},
            },
            family_id,
        ]
    )

    with patch("src.core.memory.event_log.log_action", new_callable=AsyncMock) as mock_log:
        payload = await record_memory_event(
            session,
            user_id=user_id,
            store="rule",
            slot="rule:reply briefly",
            action=MEMORY_TOMBSTONE_ACTION,
            old_value="reply briefly",
            new_value=None,
            metadata={"source": "active_rules"},
        )

    assert payload["version"] == 2
    assert payload["tombstoned"] is True
    assert payload["value"] is None
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["new_data"]["tombstoned"] is True
    assert call_kwargs["new_data"]["version"] == 2
    assert call_kwargs["new_data"]["metadata"]["source"] == "active_rules"


async def test_list_memory_history_returns_latest_entries():
    user_id = str(uuid.uuid4())
    session = AsyncMock()
    row = SimpleNamespace(
        id=15,
        action=MEMORY_UPSERT_ACTION,
        old_data={
            "store": "identity",
            "slot": "identity:name",
            "version": 1,
            "value": "Maria",
            "metadata": {"category": "user_identity"},
        },
        new_data={
            "store": "identity",
            "slot": "identity:name",
            "version": 2,
            "value": "Mary",
            "tombstoned": False,
            "metadata": {"category": "user_identity", "field": "name"},
        },
        created_at=datetime(2026, 3, 13, 12, 0, tzinfo=UTC),
    )
    result = MagicMock()
    result.scalars.return_value = [row]
    session.execute = AsyncMock(return_value=result)

    history = await list_memory_history(
        user_id,
        store="identity",
        slot="identity:name",
        limit=5,
        session=session,
    )

    assert history == [
        {
            "audit_id": 15,
            "action": MEMORY_UPSERT_ACTION,
            "store": "identity",
            "slot": "identity:name",
            "version": 2,
            "value": "Mary",
            "previous_value": "Maria",
            "tombstoned": False,
            "metadata": {"category": "user_identity", "field": "name"},
            "created_at": "2026-03-13T12:00:00+00:00",
        }
    ]
