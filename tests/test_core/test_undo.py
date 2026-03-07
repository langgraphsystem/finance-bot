"""Tests for undo window + Mem0 sync (Phase 9)."""

import json
import sys
import uuid
from types import ModuleType
from unittest.mock import AsyncMock, patch

from src.core.undo import (
    TABLE_MODEL_MAP,
    UNDO_INTENTS,
    execute_undo,
    pop_undo,
    store_undo,
)


class TestStoreUndo:
    async def test_stores_payload_with_transaction_id(self):
        mock_redis = AsyncMock()
        uid = str(uuid.uuid4())
        record_id = str(uuid.uuid4())

        with patch("src.core.undo.redis", mock_redis):
            await store_undo(uid, "add_expense", record_id, "transactions")

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        payload = json.loads(call_args[0][1])
        assert payload["transaction_id"] == record_id
        assert payload["record_id"] == record_id
        assert payload["table"] == "transactions"
        assert call_args[1]["ex"] == 120


class TestPopUndo:
    async def test_returns_payload_and_deletes_key(self):
        uid = str(uuid.uuid4())
        record_id = str(uuid.uuid4())
        payload = json.dumps({
            "intent": "add_expense",
            "record_id": record_id,
            "table": "transactions",
            "transaction_id": record_id,
        })
        mock_redis = AsyncMock()
        mock_redis.get.return_value = payload

        with patch("src.core.undo.redis", mock_redis):
            result = await pop_undo(uid)

        assert result["record_id"] == record_id
        assert result["transaction_id"] == record_id
        mock_redis.delete.assert_awaited_once()

    async def test_returns_none_when_expired(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("src.core.undo.redis", mock_redis):
            result = await pop_undo(str(uuid.uuid4()))

        assert result is None


class TestExecuteUndo:
    async def test_deletes_record_and_cleans_mem0(self):
        uid = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        record_id = str(uuid.uuid4())

        payload = json.dumps({
            "intent": "add_expense",
            "record_id": record_id,
            "table": "transactions",
            "transaction_id": record_id,
        })
        mock_redis = AsyncMock()
        mock_redis.get.return_value = payload

        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with (
            patch("src.core.undo.redis", mock_redis),
            patch("src.core.undo.async_session", return_value=mock_ctx),
            patch("src.core.undo._cleanup_mem0_facts", new_callable=AsyncMock) as mock_cleanup,
        ):
            result = await execute_undo(uid, fid)

        assert result == "Undone."
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_cleanup.assert_awaited_once_with(uid, record_id)

    async def test_returns_message_when_expired(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("src.core.undo.redis", mock_redis):
            result = await execute_undo(str(uuid.uuid4()), str(uuid.uuid4()))

        assert "expired" in result.lower() or "nothing" in result.lower()


class TestCleanupMem0Facts:
    async def test_deletes_facts_with_matching_transaction_id(self):
        from src.core.undo import _cleanup_mem0_facts

        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        mem_id = "mem-123"

        mock_search = AsyncMock(side_effect=[
            [{"id": mem_id, "metadata": {"transaction_id": tid}}],
            [{"id": mem_id, "metadata": {"transaction_id": tid}}],
        ])
        mock_delete = AsyncMock()

        # Mock the lazy import target
        fake_mod = ModuleType("src.core.memory.mem0_client")
        fake_mod.search_memories = mock_search
        fake_mod.delete_memory = mock_delete

        with patch.dict(sys.modules, {"src.core.memory.mem0_client": fake_mod}):
            await _cleanup_mem0_facts(uid, tid)

        mock_delete.assert_awaited_once_with(mem_id, uid)

    async def test_skips_facts_without_matching_transaction_id(self):
        from src.core.undo import _cleanup_mem0_facts

        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        other_tid = str(uuid.uuid4())

        mock_search = AsyncMock(side_effect=[
            Exception("filter not supported"),
            [{"id": "mem-456", "metadata": {"transaction_id": other_tid}}],
        ])
        mock_delete = AsyncMock()

        fake_mod = ModuleType("src.core.memory.mem0_client")
        fake_mod.search_memories = mock_search
        fake_mod.delete_memory = mock_delete

        with patch.dict(sys.modules, {"src.core.memory.mem0_client": fake_mod}):
            await _cleanup_mem0_facts(uid, tid)

        mock_delete.assert_not_awaited()

    async def test_handles_mem0_failure_gracefully(self):
        from src.core.undo import _cleanup_mem0_facts

        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        mock_search = AsyncMock(side_effect=Exception("Mem0 down"))
        mock_delete = AsyncMock()

        fake_mod = ModuleType("src.core.memory.mem0_client")
        fake_mod.search_memories = mock_search
        fake_mod.delete_memory = mock_delete

        with patch.dict(sys.modules, {"src.core.memory.mem0_client": fake_mod}):
            # Should not raise
            await _cleanup_mem0_facts(uid, tid)


class TestUndoIntents:
    def test_expected_intents(self):
        assert "add_expense" in UNDO_INTENTS
        assert "add_income" in UNDO_INTENTS
        assert "create_task" in UNDO_INTENTS
        assert "track_food" in UNDO_INTENTS
        assert "track_drink" in UNDO_INTENTS

    def test_table_model_map_covers_undo_tables(self):
        assert "transactions" in TABLE_MODEL_MAP
        assert "tasks" in TABLE_MODEL_MAP
        assert "life_events" in TABLE_MODEL_MAP
