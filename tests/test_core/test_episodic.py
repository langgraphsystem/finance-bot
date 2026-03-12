"""Tests for Episodic Memory (Phase 3.2)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.episodic import (
    EPISODIC_INTENTS,
    MAX_EPISODE_CONTEXT,
    extract_episode_metadata,
    format_episodes_block,
    get_recent_episodes,
    search_episodes,
    store_episode,
)


def _make_user_context(session_id: uuid.UUID) -> MagicMock:
    ctx = MagicMock()
    ctx.session_id = session_id
    ctx.updated_at = datetime.now(UTC)
    ctx.message_count = 1
    return ctx


# ---------------------------------------------------------------------------
# store_episode
# ---------------------------------------------------------------------------
class TestStoreEpisode:
    async def test_stores_on_existing_summary(self):
        session_id = uuid.uuid4()
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_ctx_result = MagicMock()
        mock_ctx_result.scalar_one_or_none.return_value = _make_user_context(session_id)
        mock_summary_result = MagicMock()
        mock_summary_result.scalar_one_or_none.return_value = mock_summary
        mock_session.execute = AsyncMock(side_effect=[mock_ctx_result, mock_summary_result])

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        fid = "00000000-0000-0000-0000-000000000002"

        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, fid, "generate_presentation", {"slides": 10})

        episodes = mock_summary.episode_metadata["episodes"]
        assert len(episodes) == 1
        assert episodes[0]["intent"] == "generate_presentation"
        assert episodes[0]["result"]["slides"] == 10
        mock_session.commit.assert_called_once()

    async def test_appends_to_existing_episodes(self):
        session_id = uuid.uuid4()
        existing_ep = {"intent": "draft_message", "timestamp": "2026-03-01", "result": {}}
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": [existing_ep]}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_ctx_result = MagicMock()
        mock_ctx_result.scalar_one_or_none.return_value = _make_user_context(session_id)
        mock_summary_result = MagicMock()
        mock_summary_result.scalar_one_or_none.return_value = mock_summary
        mock_session.execute = AsyncMock(side_effect=[mock_ctx_result, mock_summary_result])

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        fid = "00000000-0000-0000-0000-000000000002"

        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, fid, "write_post", {"topic": "AI"})

        episodes = mock_summary.episode_metadata["episodes"]
        assert len(episodes) == 2

    async def test_creates_placeholder_summary_when_missing(self):
        session_id = uuid.uuid4()
        family_id = str(uuid.uuid4())
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_ctx_result = MagicMock()
        mock_ctx_result.scalar_one_or_none.return_value = _make_user_context(session_id)
        mock_summary_result = MagicMock()
        mock_summary_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(side_effect=[mock_ctx_result, mock_summary_result])

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"

        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, family_id, "test")

        mock_session.add.assert_called_once()
        created_summary = mock_session.add.call_args.args[0]
        assert created_summary.session_id == session_id
        mock_session.commit.assert_called_once()

    async def test_caps_at_10_episodes(self):
        session_id = uuid.uuid4()
        old_eps = [{"intent": f"intent_{i}", "result": {}} for i in range(10)]
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": old_eps}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_ctx_result = MagicMock()
        mock_ctx_result.scalar_one_or_none.return_value = _make_user_context(session_id)
        mock_summary_result = MagicMock()
        mock_summary_result.scalar_one_or_none.return_value = mock_summary
        mock_session.execute = AsyncMock(side_effect=[mock_ctx_result, mock_summary_result])

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        family_id = str(uuid.uuid4())

        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, family_id, "new_intent")

        episodes = mock_summary.episode_metadata["episodes"]
        assert len(episodes) == 10
        assert episodes[-1]["intent"] == "new_intent"

    async def test_db_failure_graceful(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, str(uuid.uuid4()), "test")


# ---------------------------------------------------------------------------
# search_episodes
# ---------------------------------------------------------------------------
class TestSearchEpisodes:
    async def test_finds_by_intent(self):
        ep = {"intent": "generate_presentation", "result": {"slides": 10}}
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": [ep]}
        mock_summary.summary = "Created presentation about AI"
        mock_summary.updated_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await search_episodes(
                uid, "presentation", intent="generate_presentation"
            )

        assert len(result) == 1
        assert result[0]["intent"] == "generate_presentation"

    async def test_store_episode_uses_current_session_summary(self):
        session_id = uuid.uuid4()
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {}

        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        async def _mock_execute(stmt):
            query = str(stmt)
            result = MagicMock()
            if "FROM user_context" in query:
                result.scalar_one_or_none.return_value = _make_user_context(session_id)
            else:
                result.scalar_one_or_none.return_value = mock_summary
            return result

        mock_session.execute = AsyncMock(side_effect=_mock_execute)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        fid = "00000000-0000-0000-0000-000000000002"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            await store_episode(uid, fid, "write_post", {"topic": "AI"})

        summary_query = mock_session.execute.await_args_list[1].args[0]
        assert "session_summaries.session_id" in str(summary_query)

    async def test_finds_by_topic_in_result(self):
        ep = {"intent": "write_post", "result": {"topic": "machine learning"}}
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": [ep]}
        mock_summary.summary = "Wrote a blog post about ML"
        mock_summary.updated_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await search_episodes(uid, "machine learning")

        assert len(result) == 1

    async def test_respects_limit(self):
        eps = [
            {"intent": "write_post", "result": {"n": i}}
            for i in range(10)
        ]
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": eps}
        mock_summary.summary = "Multiple posts"
        mock_summary.updated_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await search_episodes(uid, "post", limit=2)

        assert len(result) <= 2

    async def test_empty_on_no_matches(self):
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": []}
        mock_summary.summary = "test"
        mock_summary.updated_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await search_episodes(uid, "nonexistent")

        assert result == []

    async def test_db_failure_returns_empty(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await search_episodes(uid, "test")
        assert result == []


# ---------------------------------------------------------------------------
# get_recent_episodes
# ---------------------------------------------------------------------------
class TestGetRecentEpisodes:
    async def test_returns_recent(self):
        ep = {"intent": "draft_message", "result": {"to": "john"}}
        mock_summary = MagicMock()
        mock_summary.episode_metadata = {"episodes": [ep]}
        mock_summary.summary = "Drafted email to John"
        mock_summary.updated_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await get_recent_episodes(uid)

        assert len(result) == 1
        assert result[0]["intent"] == "draft_message"

    async def test_empty_on_db_failure(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch("src.core.memory.episodic.async_session", return_value=mock_ctx):
            result = await get_recent_episodes(uid)
        assert result == []


# ---------------------------------------------------------------------------
# extract_episode_metadata
# ---------------------------------------------------------------------------
class TestExtractEpisodeMetadata:
    async def test_parses_json_response(self):
        mock_response = MagicMock()
        mock_response.text = '{"topics": ["finance"], "outcome": "completed"}'
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_episode_metadata("Summary of dialog")

        assert result["topics"] == ["finance"]
        assert result["outcome"] == "completed"

    async def test_handles_code_fences(self):
        mock_response = MagicMock()
        mock_response.text = (
            '```json\n{"topics": ["AI"], "outcome": "completed"}\n```'
        )
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_episode_metadata("Summary")

        assert result["topics"] == ["AI"]

    async def test_llm_failure_returns_empty(self):
        with patch(
            "src.core.llm.clients.google_client",
            side_effect=Exception("API down"),
        ):
            result = await extract_episode_metadata("Summary")
        assert result == {}

    async def test_invalid_json_returns_empty(self):
        mock_response = MagicMock()
        mock_response.text = "not valid json"
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_episode_metadata("Summary")
        assert result == {}


# ---------------------------------------------------------------------------
# format_episodes_block
# ---------------------------------------------------------------------------
class TestFormatEpisodesBlock:
    def test_empty_returns_empty(self):
        assert format_episodes_block([]) == ""

    def test_formats_with_tags(self):
        eps = [
            {
                "intent": "generate_presentation",
                "date": "2026-03-01T12:00:00",
                "result": {"slides": 10, "style": "modern"},
                "summary": "Created AI presentation",
            }
        ]
        result = format_episodes_block(eps)
        assert "<past_episodes>" in result
        assert "</past_episodes>" in result
        assert "generate_presentation" in result
        assert "slides=10" in result

    def test_caps_at_max_context(self):
        eps = [
            {"intent": f"intent_{i}", "date": "2026-03-01", "result": {}, "summary": ""}
            for i in range(10)
        ]
        result = format_episodes_block(eps)
        # Should only include MAX_EPISODE_CONTEXT episodes
        assert result.count("intent_") == MAX_EPISODE_CONTEXT

    def test_no_result_params(self):
        eps = [{"intent": "test", "date": "2026-03-01", "result": {}, "summary": ""}]
        result = format_episodes_block(eps)
        assert "params:" not in result


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_episodic_intents(self):
        assert "generate_presentation" in EPISODIC_INTENTS
        assert "generate_spreadsheet" in EPISODIC_INTENTS
        assert "complex_query" in EPISODIC_INTENTS
        assert "add_expense" not in EPISODIC_INTENTS

    def test_max_episode_context(self):
        assert MAX_EPISODE_CONTEXT == 3
