"""Tests for Mem0 client - URL builder and namespace helpers."""

import sys
import types
from unittest.mock import patch

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

from src.core.memory.mem0_client import (  # noqa: E402
    _all_namespace_user_ids,
    _build_pgvector_url,
    _PatchedConnectionPool,
    search_memories_multi_domain,
)
from src.core.memory.mem0_domains import MemoryDomain  # noqa: E402


def test_build_url_strips_asyncpg():
    url = "postgresql+asyncpg://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert result.startswith("postgresql://")
    assert "+asyncpg" not in result



def test_build_url_normalizes_postgres_prefix():
    url = "postgres://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert result.startswith("postgresql://")



def test_build_url_adds_sslmode_for_remote():
    url = "postgresql://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode=require" in result



def test_build_url_no_ssl_for_localhost():
    url = "postgresql://user:pass@localhost:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode" not in result



def test_build_url_no_ssl_for_127():
    url = "postgresql://user:pass@127.0.0.1:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode" not in result



def test_build_url_preserves_existing_sslmode():
    url = "postgresql://user:pass@db.supabase.co:5432/postgres?sslmode=verify-full"
    result = _build_pgvector_url(url)
    assert "sslmode=verify-full" in result
    assert result.count("sslmode") == 1



def test_build_url_preserves_other_params():
    url = "postgresql://user:pass@db.supabase.co:5432/postgres?connect_timeout=10"
    result = _build_pgvector_url(url)
    assert "connect_timeout=10" in result
    assert "sslmode=require" in result



def test_patched_connection_pool_disables_prepared_statements():
    captured: dict[str, object] = {}

    def fake_init(self, *args, **kwargs):
        captured["kwargs"] = kwargs

    with patch("src.core.memory.mem0_client._OrigConnectionPool.__init__", new=fake_init):
        _PatchedConnectionPool(conninfo="postgresql://user:pass@localhost/postgres")

    kwargs = captured["kwargs"]
    assert kwargs["kwargs"]["prepare_threshold"] is None

    conn = type("Conn", (), {"prepare_threshold": 5})()
    kwargs["configure"](conn)
    assert conn.prepare_threshold is None



def test_all_namespace_user_ids_include_legacy_and_scoped_namespaces():
    namespaces = _all_namespace_user_ids("u1")

    assert namespaces[0] == "u1"
    assert len(namespaces) == len(MemoryDomain) + 1
    assert "u1:core" in namespaces
    assert "u1:life" in namespaces


def test_read_only_mem0_user_id_does_not_write():
    from src.core.memory.mem0_client import _read_only_mem0_user_id

    setup = types.SimpleNamespace(get_user_id=lambda: "mem0-user")

    assert _read_only_mem0_user_id(setup) == "mem0-user"


def test_read_only_mem0_user_id_falls_back_to_anonymous():
    from src.core.memory.mem0_client import _read_only_mem0_user_id

    setup = types.SimpleNamespace(get_user_id=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert _read_only_mem0_user_id(setup) == "anonymous_user"


async def test_multi_domain_timeout_returns_partial_results():
    import asyncio

    async def fake_search(query, user_id, limit=10, filters=None, domain=None):
        if domain == MemoryDomain.core:
            return [{"memory": "core result", "metadata": {}}]
        await asyncio.sleep(0.05)
        return [{"memory": "late result", "metadata": {}}]

    async def fake_wait(tasks, timeout):
        done = {tasks[0]}
        pending = {tasks[1]}
        await asyncio.sleep(0)
        return done, pending

    with (
        patch("src.core.memory.mem0_client.search_memories", new=fake_search),
        patch("asyncio.wait", new=fake_wait),
    ):
        results = await search_memories_multi_domain(
            "salary",
            "user-1",
            [MemoryDomain.core, MemoryDomain.finance],
        )

    assert results == [{"memory": "core result", "metadata": {}}]
