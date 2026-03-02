"""Tests for graph state recovery module."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrators.recovery import get_dlq_entries, recover_pending_graphs


class TestRecoverPendingGraphs:
    async def test_skips_when_checkpointer_disabled(self):
        with patch("src.core.config.settings") as mock_settings:
            mock_settings.ff_langgraph_checkpointer = False
            stats = await recover_pending_graphs()

        assert stats == {"hitl_pending": 0, "recovered": 0}

    async def test_skips_when_no_alist(self):
        mock_cp = MagicMock()
        del mock_cp.alist  # no alist method

        with (
            patch("src.core.config.settings") as mock_settings,
            patch(
                "src.orchestrators.checkpointer.get_checkpointer",
                return_value=mock_cp,
            ),
        ):
            mock_settings.ff_langgraph_checkpointer = True
            stats = await recover_pending_graphs()

        assert stats == {"hitl_pending": 0, "recovered": 0}

    async def test_counts_pending_hitl_threads(self):
        checkpoint_tuple = MagicMock()
        checkpoint_tuple.config = {
            "configurable": {"thread_id": "email-user1-send_email-123"}
        }
        checkpoint_tuple.checkpoint = {
            "pending_sends": [{"type": "email_approval"}],
        }

        async def mock_alist(config):
            yield checkpoint_tuple

        mock_cp = MagicMock()
        mock_cp.alist = mock_alist

        with (
            patch("src.core.config.settings") as mock_settings,
            patch(
                "src.orchestrators.checkpointer.get_checkpointer",
                return_value=mock_cp,
            ),
        ):
            mock_settings.ff_langgraph_checkpointer = True
            stats = await recover_pending_graphs()

        assert stats["hitl_pending"] == 1

    async def test_handles_checkpointer_error_gracefully(self):
        with (
            patch("src.core.config.settings") as mock_settings,
            patch(
                "src.orchestrators.checkpointer.get_checkpointer",
                side_effect=Exception("boom"),
            ),
        ):
            mock_settings.ff_langgraph_checkpointer = True
            stats = await recover_pending_graphs()

        assert stats == {"hitl_pending": 0, "recovered": 0}


class TestGetDlqEntries:
    async def test_fetches_entries(self):
        mock_entry = MagicMock()
        mock_entry.id = "dlq-id-1"
        mock_entry.graph_name = "email"
        mock_entry.thread_id = "email-thread-1"
        mock_entry.user_id = "user-1"
        mock_entry.error = "TimeoutError"
        mock_entry.retried = False
        mock_entry.created_at = MagicMock(isoformat=lambda: "2026-03-01T12:00:00")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_entry]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            entries = await get_dlq_entries(graph_name="email", limit=5)

        assert len(entries) == 1
        assert entries[0]["graph_name"] == "email"

    async def test_handles_db_error(self):
        with patch(
            "src.core.db.async_session",
            side_effect=Exception("DB down"),
        ):
            entries = await get_dlq_entries()
        assert entries == []
