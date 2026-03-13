"""Tests for GDPR memory registry integration."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.gdpr import MemoryGDPR


def _result(items):
    result = MagicMock()
    result.scalars.return_value = items
    return result


async def test_export_user_data_includes_memory_registry():
    user_id = str(uuid.uuid4())
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([]),  # transactions
            _result([]),  # messages
            _result([]),  # summaries
            _result([]),  # life events
            _result([]),  # tasks
            _result([]),  # scheduled actions
            _result([]),  # projects
            _result([]),  # contacts
            _result([]),  # bookings
            _result([]),  # documents
        ]
    )
    session.scalar = AsyncMock(return_value=None)

    with (
        patch("src.core.gdpr.get_all_memories", new_callable=AsyncMock, return_value=[]),
        patch(
            "src.core.gdpr.export_memory_registry",
            new_callable=AsyncMock,
            return_value=[{"id": "identity:name", "store": "identity", "text": "Alice"}],
        ),
    ):
        payload = await MemoryGDPR().export_user_data(session, user_id)

    assert payload["memory_registry"] == [
        {"id": "identity:name", "store": "identity", "text": "Alice"}
    ]


async def test_delete_user_data_uses_unified_memory_registry_clear():
    user_id = str(uuid.uuid4())
    uid = uuid.UUID(user_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_result([])] + [MagicMock()] * 12)
    session.commit = AsyncMock()

    async def _empty_scan_iter(match):  # noqa: ARG001
        if False:
            yield None

    with (
        patch("src.core.gdpr.clear_memory_registry", new_callable=AsyncMock) as mock_clear,
        patch("src.core.gdpr.redis.scan_iter", side_effect=_empty_scan_iter),
        patch("src.core.gdpr.redis.delete", new_callable=AsyncMock),
    ):
        deleted = await MemoryGDPR().delete_user_data(session, user_id)

    assert deleted is True
    session.execute.assert_awaited()
    session.commit.assert_awaited_once()
    mock_clear.assert_awaited_once_with(
        str(uid),
        session=session,
        include_stores={"mem0", "identity", "rule", "summary"},
    )
