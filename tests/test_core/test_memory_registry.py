"""Tests for the canonical memory registry."""

import sys
import types
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

for module_name in (
    "psycopg_pool",
    "mem0",
    "mem0.vector_stores",
    "mem0.vector_stores.pgvector",
):
    if module_name not in sys.modules:
        sys.modules[module_name] = types.ModuleType(module_name)

pool_mod = sys.modules["psycopg_pool"]
if not hasattr(pool_mod, "ConnectionPool"):
    class _DummyConnectionPool:
        def __init__(self, *args, **kwargs):
            pass

    pool_mod.ConnectionPool = _DummyConnectionPool  # type: ignore[attr-defined]

mem0_mod = sys.modules["mem0"]
if not hasattr(mem0_mod, "Memory"):
    class _DummyMemory:
        @classmethod
        def from_config(cls, config):
            return cls()

    mem0_mod.Memory = _DummyMemory  # type: ignore[attr-defined]

pgvector_mod = sys.modules["mem0.vector_stores.pgvector"]
if not hasattr(pgvector_mod, "ConnectionPool"):
    pgvector_mod.ConnectionPool = pool_mod.ConnectionPool  # type: ignore[attr-defined]

from src.core.memory.registry import (  # noqa: E402
    clear_memory_registry,
    delete_registry_entry,
    list_memory_registry,
    search_memory_registry,
    write_canonical_memory,
)


def _summary_context(summary_rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value = summary_rows
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return session, ctx


async def test_list_memory_registry_aggregates_mem0_identity_rules_and_summaries():
    user_id = str(uuid.uuid4())
    summary = SimpleNamespace(
        id=7,
        session_id=uuid.uuid4(),
        summary="Discussed tax reminders",
        created_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 3, 2, 9, 30, tzinfo=UTC),
    )
    _, ctx = _summary_context([summary])

    with (
        patch(
            "src.core.memory.registry.identity_store.get_core_identity",
            new_callable=AsyncMock,
            return_value={"name": "Alice", "city": "Chicago"},
        ),
        patch(
            "src.core.memory.registry.identity_store.get_user_rules",
            new_callable=AsyncMock,
            return_value=["reply briefly"],
        ),
        patch(
            "src.core.memory.registry.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "mem-1",
                    "memory": "Likes jasmine tea",
                    "metadata": {"category": "life_note", "source": "memory_vault"},
                }
            ],
        ),
        patch("src.core.memory.registry.async_session", return_value=ctx),
    ):
        entries = await list_memory_registry(user_id)

    stores = {entry["store"] for entry in entries}
    assert stores == {"identity", "rule", "mem0", "summary"}
    assert any(entry["id"] == "identity:name" and entry["text"] == "Alice" for entry in entries)
    assert any(entry["store"] == "rule" and entry["text"] == "reply briefly" for entry in entries)
    assert any(entry["id"] == "mem0:mem-1" for entry in entries)
    assert any(entry["id"] == "summary:7" for entry in entries)


async def test_search_memory_registry_merges_mem0_and_structured_matches():
    with (
        patch(
            "src.core.memory.registry.mem0_client.search_memories_all_namespaces",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "mem-1",
                    "memory": "User likes coffee",
                    "metadata": {"category": "life_note"},
                    "score": 0.82,
                }
            ],
        ),
        patch(
            "src.core.memory.registry.list_memory_registry",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "summary:3",
                    "store": "summary",
                    "source_id": "3",
                    "text": "Coffee expenses spike every Monday",
                    "display_text": "Coffee expenses spike every Monday",
                }
            ],
        ),
    ):
        matches = await search_memory_registry("user-1", "coffee", limit=5)

    assert {entry["id"] for entry in matches} == {"mem0:mem-1", "summary:3"}


async def test_list_memory_registry_hides_shadowed_mem0_identity_duplicates():
    user_id = str(uuid.uuid4())
    _, ctx = _summary_context([])

    with (
        patch(
            "src.core.memory.registry.identity_store.get_core_identity",
            new_callable=AsyncMock,
            return_value={"name": "Alice"},
        ),
        patch(
            "src.core.memory.registry.identity_store.get_user_rules",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.core.memory.registry.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[
                {
                    "id": "mem-shadowed",
                    "memory": "My name is Alice",
                    "metadata": {"category": "user_identity"},
                },
                {
                    "id": "mem-keep",
                    "memory": "Likes green tea",
                    "metadata": {"category": "life_note"},
                },
            ],
        ),
        patch("src.core.memory.registry.async_session", return_value=ctx),
    ):
        entries = await list_memory_registry(user_id)

    entry_ids = {entry["id"] for entry in entries}
    assert "mem0:mem-shadowed" not in entry_ids
    assert "mem0:mem-keep" in entry_ids


async def test_write_canonical_memory_updates_structured_store_and_cleans_duplicates():
    with (
        patch(
            "src.core.memory.registry.identity_store.get_core_identity",
            new_callable=AsyncMock,
            side_effect=[{}, {"name": "Alice"}],
        ),
        patch(
            "src.core.memory.registry.identity_store.get_user_rules",
            new_callable=AsyncMock,
            side_effect=[[], []],
        ),
        patch(
            "src.core.memory.registry.identity_store.immediate_identity_update",
            new_callable=AsyncMock,
        ) as mock_update,
        patch(
            "src.core.memory.registry.cleanup_shadowed_mem0_memories",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_cleanup,
    ):
        result = await write_canonical_memory(
            "user-1",
            "My name is Alice",
            source="memory_vault",
            category="user_identity",
        )

    assert result["store"] == "identity"
    assert result["updated_fields"] == ["name"]
    assert result["deleted_duplicates"] == 2
    mock_update.assert_awaited_once_with("user-1", "user_identity", "My name is Alice")
    mock_cleanup.assert_awaited_once()


async def test_write_canonical_memory_versions_nonstructured_mem0_replacements():
    with patch(
        "src.core.memory.registry.mem0_client.add_memory",
        new_callable=AsyncMock,
        return_value={"id": "mem-new"},
    ) as mock_add:
        await write_canonical_memory(
            "user-1",
            "Remember this note",
            source="memory_update",
            category="life_note",
            existing_memory={
                "id": "mem-old",
                "source_id": "mem-old",
                "metadata": {"category": "life_note", "version": 2},
            },
        )

    call_kwargs = mock_add.call_args.kwargs
    assert call_kwargs["metadata"]["version"] == 3
    assert call_kwargs["metadata"]["supersedes"] == "mem-old"


async def test_delete_registry_entry_deletes_summary_with_provided_session():
    user_id = str(uuid.uuid4())
    session = AsyncMock()

    deleted = await delete_registry_entry(
        user_id,
        {"id": "summary:12", "store": "summary", "source_id": "12"},
        session=session,
    )

    assert deleted is True
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_clear_memory_registry_clears_all_supported_stores():
    user_id = str(uuid.uuid4())
    session, ctx = _summary_context([1, 2])

    with (
        patch(
            "src.core.memory.registry.mem0_client.get_all_memories",
            new_callable=AsyncMock,
            return_value=[{"id": "m1"}, {"id": "m2"}],
        ),
        patch(
            "src.core.memory.registry.mem0_client.delete_all_memories",
            new_callable=AsyncMock,
        ) as mock_del_all,
        patch(
            "src.core.memory.registry.identity_store.clear_user_rules",
            new_callable=AsyncMock,
            return_value=3,
        ),
        patch(
            "src.core.memory.registry.identity_store.get_core_identity",
            new_callable=AsyncMock,
            return_value={"name": "Alice", "bot_name": "Memo"},
        ),
        patch(
            "src.core.memory.registry.identity_store.clear_identity_fields",
            new_callable=AsyncMock,
            return_value=["name", "bot_name"],
        ) as mock_clear_identity,
        patch(
            "src.core.memory.registry.identity_store.invalidate_identity_cache",
            new_callable=AsyncMock,
        ) as mock_invalidate,
        patch("src.core.memory.registry.async_session", return_value=ctx),
    ):
        counts = await clear_memory_registry(user_id)

    assert counts == {"mem0": 2, "identity": 2, "rule": 3, "summary": 2}
    mock_del_all.assert_awaited_once_with(user_id)
    mock_clear_identity.assert_awaited_once_with(user_id, ["name", "bot_name"])
    mock_invalidate.assert_awaited_once_with(user_id)
    session.execute.assert_awaited()
    session.commit.assert_awaited_once()
