"""Tests for Mem0 client — URL builder and error handling."""

from src.core.memory.mem0_client import _build_pgvector_url


def test_build_url_strips_asyncpg():
    """Should strip +asyncpg driver prefix."""
    url = "postgresql+asyncpg://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert result.startswith("postgresql://")
    assert "+asyncpg" not in result


def test_build_url_normalizes_postgres_prefix():
    """Should normalize postgres:// to postgresql://."""
    url = "postgres://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert result.startswith("postgresql://")


def test_build_url_adds_sslmode_for_remote():
    """Should add sslmode=require for remote databases."""
    url = "postgresql://user:pass@db.supabase.co:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode=require" in result


def test_build_url_no_ssl_for_localhost():
    """Should NOT add sslmode for localhost."""
    url = "postgresql://user:pass@localhost:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode" not in result


def test_build_url_no_ssl_for_127():
    """Should NOT add sslmode for 127.0.0.1."""
    url = "postgresql://user:pass@127.0.0.1:5432/postgres"
    result = _build_pgvector_url(url)
    assert "sslmode" not in result


def test_build_url_preserves_existing_sslmode():
    """Should preserve existing sslmode in URL."""
    url = "postgresql://user:pass@db.supabase.co:5432/postgres?sslmode=verify-full"
    result = _build_pgvector_url(url)
    assert "sslmode=verify-full" in result
    # Should NOT have duplicate sslmode
    assert result.count("sslmode") == 1


def test_build_url_preserves_other_params():
    """Should preserve other query params."""
    url = "postgresql://user:pass@db.supabase.co:5432/postgres?connect_timeout=10"
    result = _build_pgvector_url(url)
    assert "connect_timeout=10" in result
    assert "sslmode=require" in result
