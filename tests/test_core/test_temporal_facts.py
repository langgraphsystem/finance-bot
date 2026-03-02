"""Tests for temporal fact tracking (Phase 2.4)."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.mem0_client import _archive_superseded_fact, add_memory
from src.core.memory.mem0_domains import MemoryDomain


class TestArchiveSupersededFact:
    async def test_archives_similar_fact(self):
        old_memory = {"memory": "salary 5000", "score": 0.92}
        with (
            patch(
                "src.core.memory.mem0_client.search_memories",
                new_callable=AsyncMock,
                return_value=[old_memory],
            ),
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
            patch("src.core.memory.mem0_client._resolve_user_id", return_value="u1:finance"),
        ):
            mock_mem = MagicMock()
            mock_get_mem.return_value = mock_mem

            await _archive_superseded_fact(
                "salary 6000", "u1", MemoryDomain.finance, "income"
            )

            mock_mem.add.assert_called_once()
            call_args = mock_mem.add.call_args
            assert "[Archived] salary 5000" in call_args[0][0]
            metadata = call_args[1].get("metadata", {})
            assert metadata["category"] == "fact_history"
            assert metadata["old_value"] == "salary 5000"
            assert metadata["new_value"] == "salary 6000"
            assert "superseded_at" in metadata

    async def test_skips_non_updatable_category(self):
        with patch(
            "src.core.memory.mem0_client.search_memories",
            new_callable=AsyncMock,
        ) as mock_search:
            await _archive_superseded_fact(
                "went for a walk", "u1", MemoryDomain.life, "life_note"
            )
            # life_note is not in UPDATABLE_CATEGORIES
            mock_search.assert_not_called()

    async def test_skips_low_similarity(self):
        low_sim = {"memory": "something unrelated", "score": 0.5}
        with (
            patch(
                "src.core.memory.mem0_client.search_memories",
                new_callable=AsyncMock,
                return_value=[low_sim],
            ),
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_mem = MagicMock()
            mock_get_mem.return_value = mock_mem

            await _archive_superseded_fact(
                "salary 6000", "u1", MemoryDomain.finance, "income"
            )
            mock_mem.add.assert_not_called()

    async def test_skips_identical_content(self):
        same = {"memory": "salary 6000", "score": 0.99}
        with (
            patch(
                "src.core.memory.mem0_client.search_memories",
                new_callable=AsyncMock,
                return_value=[same],
            ),
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_mem = MagicMock()
            mock_get_mem.return_value = mock_mem

            await _archive_superseded_fact(
                "salary 6000", "u1", MemoryDomain.finance, "income"
            )
            mock_mem.add.assert_not_called()

    async def test_skips_when_no_existing(self):
        with (
            patch(
                "src.core.memory.mem0_client.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_mem = MagicMock()
            mock_get_mem.return_value = mock_mem

            await _archive_superseded_fact(
                "salary 6000", "u1", MemoryDomain.finance, "income"
            )
            mock_mem.add.assert_not_called()

    async def test_graceful_on_error(self):
        with patch(
            "src.core.memory.mem0_client.search_memories",
            new_callable=AsyncMock,
            side_effect=Exception("search failed"),
        ):
            # Should not raise
            await _archive_superseded_fact(
                "salary 6000", "u1", MemoryDomain.finance, "income"
            )


class TestAddMemoryWithTemporal:
    async def test_calls_archive_for_updatable_category(self):
        with (
            patch("src.core.memory.mem0_client.get_circuit") as mock_gc,
            patch(
                "src.core.memory.mem0_client._archive_superseded_fact",
                new_callable=AsyncMock,
            ) as mock_archive,
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_gc.return_value = mock_cb
            mock_mem = MagicMock()
            mock_mem.add.return_value = {"id": "123"}
            mock_get_mem.return_value = mock_mem

            await add_memory(
                "salary 6000", "u1", metadata={"category": "income"}
            )
            mock_archive.assert_called_once()

    async def test_skips_archive_for_fact_history(self):
        with (
            patch("src.core.memory.mem0_client.get_circuit") as mock_gc,
            patch(
                "src.core.memory.mem0_client._archive_superseded_fact",
                new_callable=AsyncMock,
            ) as mock_archive,
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_gc.return_value = mock_cb
            mock_mem = MagicMock()
            mock_mem.add.return_value = {"id": "123"}
            mock_get_mem.return_value = mock_mem

            await add_memory(
                "[Archived] old fact",
                "u1",
                metadata={"category": "fact_history"},
            )
            mock_archive.assert_not_called()

    async def test_skips_archive_when_no_category(self):
        with (
            patch("src.core.memory.mem0_client.get_circuit") as mock_gc,
            patch(
                "src.core.memory.mem0_client._archive_superseded_fact",
                new_callable=AsyncMock,
            ) as mock_archive,
            patch("src.core.memory.mem0_client.get_memory") as mock_get_mem,
        ):
            mock_cb = MagicMock()
            mock_cb.can_execute.return_value = True
            mock_gc.return_value = mock_cb
            mock_mem = MagicMock()
            mock_mem.add.return_value = {"id": "123"}
            mock_get_mem.return_value = mock_mem

            await add_memory("just a note", "u1")
            mock_archive.assert_not_called()
