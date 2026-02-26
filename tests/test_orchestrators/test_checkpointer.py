"""Tests for the LangGraph checkpointer factory."""

from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver


def test_get_checkpointer_returns_memory_saver_in_testing():
    """In testing mode, get_checkpointer returns MemorySaver."""
    with patch("src.orchestrators.checkpointer.settings") as mock_settings:
        mock_settings.app_env = "testing"
        import src.orchestrators.checkpointer as mod

        mod._checkpointer = None

        cp = mod.get_checkpointer()
        assert isinstance(cp, MemorySaver)

        mod._checkpointer = None


def test_get_checkpointer_singleton():
    """Repeated calls return the same instance."""
    with patch("src.orchestrators.checkpointer.settings") as mock_settings:
        mock_settings.app_env = "testing"
        import src.orchestrators.checkpointer as mod

        mod._checkpointer = None

        cp1 = mod.get_checkpointer()
        cp2 = mod.get_checkpointer()
        assert cp1 is cp2

        mod._checkpointer = None


def test_get_checkpointer_production_uses_postgres():
    """In production mode, get_checkpointer attempts PostgreSQL saver."""
    from unittest.mock import MagicMock

    fake_saver = MagicMock(spec_set=["setup"])
    fake_module = MagicMock()
    fake_module.AsyncPostgresSaver.from_conn_string.return_value = fake_saver

    with (
        patch("src.orchestrators.checkpointer.settings") as mock_settings,
        patch.dict(
            "sys.modules",
            {"langgraph.checkpoint.postgres.aio": fake_module},
        ),
    ):
        mock_settings.app_env = "production"
        mock_settings.database_url = "postgresql://user:pass@localhost/db"

        import src.orchestrators.checkpointer as mod

        mod._checkpointer = None

        cp = mod.get_checkpointer()
        assert not isinstance(cp, MemorySaver)
        assert cp is fake_saver
        fake_module.AsyncPostgresSaver.from_conn_string.assert_called_once()

        mod._checkpointer = None
