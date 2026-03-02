"""Tests for Observational Memory — Observer + Reflector (Phase 3.1)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.observational import (
    MAX_STORED_OBSERVATIONS,
    OBSERVATION_INTENTS,
    OBSERVER_TOKEN_THRESHOLD,
    REFLECTOR_TOKEN_THRESHOLD,
    _parse_observations,
    estimate_message_tokens,
    estimate_tokens,
    extract_observations,
    format_observations_block,
    load_user_observations,
    restructure_observations,
    save_user_observations,
    should_observe,
)


# ---------------------------------------------------------------------------
# estimate_tokens / estimate_message_tokens
# ---------------------------------------------------------------------------
class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 1

    def test_short_text(self):
        assert estimate_tokens("hello") == 2  # 5 // 4 + 1

    def test_long_text(self):
        assert estimate_tokens("a" * 100) == 26  # 100 // 4 + 1


class TestEstimateMessageTokens:
    def test_empty_list(self):
        assert estimate_message_tokens([]) == 0

    def test_single_message(self):
        msgs = [{"content": "a" * 100}]
        assert estimate_message_tokens(msgs) == 26

    def test_multiple_messages(self):
        msgs = [{"content": "a" * 100}, {"content": "b" * 200}]
        assert estimate_message_tokens(msgs) == 26 + 51  # 100//4+1 + 200//4+1

    def test_missing_content(self):
        msgs = [{"role": "user"}, {"content": "test"}]
        assert estimate_message_tokens(msgs) == 1 + 2  # "" -> 1, "test" -> 2


# ---------------------------------------------------------------------------
# should_observe
# ---------------------------------------------------------------------------
class TestShouldObserve:
    def test_below_threshold(self):
        msgs = [{"content": "short msg"}]
        assert should_observe(msgs) is False

    def test_above_threshold(self):
        # 25K tokens ~ 100K chars
        msgs = [{"content": "x" * 110_000}]
        assert should_observe(msgs) is True

    def test_empty(self):
        assert should_observe([]) is False


# ---------------------------------------------------------------------------
# _parse_observations
# ---------------------------------------------------------------------------
class TestParseObservations:
    def test_dated_format(self):
        text = "[2026-03-01] Spends 500 on gas\n[2026-03-02] Coffee 3x daily"
        result = _parse_observations(text)
        assert len(result) == 2
        assert "[2026-03-01]" in result[0]
        assert "[2026-03-02]" in result[1]

    def test_adds_date_if_missing(self):
        text = "Spends a lot on coffee every day"
        result = _parse_observations(text)
        assert len(result) == 1
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert result[0].startswith(f"[{today}]")

    def test_strips_bullet_prefix(self):
        text = "- [2026-03-01] Pattern A\n- [2026-03-01] Pattern B"
        result = _parse_observations(text)
        assert len(result) == 2
        assert result[0].startswith("[2026-03-01]")

    def test_skips_empty_lines(self):
        text = "[2026-03-01] Pattern A\n\n\n[2026-03-01] Pattern B"
        result = _parse_observations(text)
        assert len(result) == 2

    def test_skips_short_undated_lines(self):
        text = "[2026-03-01] Real pattern\nshort"
        result = _parse_observations(text)
        assert len(result) == 1

    def test_empty_text(self):
        assert _parse_observations("") == []
        assert _parse_observations("   ") == []


# ---------------------------------------------------------------------------
# format_observations_block
# ---------------------------------------------------------------------------
class TestFormatObservationsBlock:
    def test_empty_returns_empty(self):
        assert format_observations_block([]) == ""

    def test_formats_with_tags(self):
        obs = ["[2026-03-01] Spends 500 on gas"]
        result = format_observations_block(obs)
        assert "<behavioral_patterns>" in result
        assert "</behavioral_patterns>" in result
        assert "- [2026-03-01] Spends 500 on gas" in result

    def test_caps_at_20(self):
        obs = [f"[2026-03-01] Observation {i}" for i in range(30)]
        result = format_observations_block(obs)
        assert result.count("- [2026-03-01]") == 20


# ---------------------------------------------------------------------------
# extract_observations
# ---------------------------------------------------------------------------
class TestExtractObservations:
    async def test_happy_path(self):
        mock_response = MagicMock()
        mock_response.text = (
            "[2026-03-01] Spends ~500 weekly on gas\n"
            "[2026-03-01] Tracks coffee daily"
        )
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_observations(
                [{"role": "user", "content": "I spent 500 on gas"}]
            )
        assert len(result) == 2
        assert "[2026-03-01]" in result[0]

    async def test_merges_with_existing(self):
        mock_response = MagicMock()
        mock_response.text = "[2026-03-01] New pattern"
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        existing = ["[2026-02-28] Old pattern"]
        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_observations(
                [{"role": "user", "content": "test"}],
                existing_observations=existing,
            )
        assert len(result) == 2
        assert result[0] == "[2026-02-28] Old pattern"
        assert "[2026-03-01]" in result[1]

    async def test_empty_messages_returns_existing(self):
        existing = ["[2026-02-28] Old"]
        result = await extract_observations([], existing_observations=existing)
        assert result == existing

    async def test_empty_messages_returns_empty(self):
        result = await extract_observations([])
        assert result == []

    async def test_llm_failure_returns_existing(self):
        existing = ["[2026-02-28] Old"]
        with patch(
            "src.core.llm.clients.google_client",
            side_effect=Exception("API down"),
        ):
            result = await extract_observations(
                [{"role": "user", "content": "test"}],
                existing_observations=existing,
            )
        assert result == existing

    async def test_skips_empty_content_messages(self):
        mock_response = MagicMock()
        mock_response.text = ""
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        msgs = [{"role": "user", "content": ""}, {"role": "user"}]
        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await extract_observations(msgs)
        assert result == []


# ---------------------------------------------------------------------------
# restructure_observations
# ---------------------------------------------------------------------------
class TestRestructureObservations:
    async def test_below_threshold_no_op(self):
        obs = ["[2026-03-01] Short observation"]
        result = await restructure_observations(obs)
        assert result == obs

    async def test_above_threshold_calls_llm(self):
        # Create observations exceeding REFLECTOR_TOKEN_THRESHOLD
        obs = [f"[2026-03-01] Observation number {i} " + "x" * 600 for i in range(250)]
        total = sum(estimate_tokens(o) for o in obs)
        assert total > REFLECTOR_TOKEN_THRESHOLD

        mock_response = MagicMock()
        mock_response.text = (
            "[2026-03-01] Merged pattern A\n[2026-03-01] Merged pattern B"
        )
        mock_model = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = mock_model

        with patch(
            "src.core.llm.clients.google_client",
            return_value=mock_client,
        ):
            result = await restructure_observations(obs)
        assert len(result) == 2
        mock_model.assert_called_once()

    async def test_llm_failure_returns_original(self):
        obs = [f"[2026-03-01] Obs {i} " + "x" * 600 for i in range(250)]

        with patch(
            "src.core.llm.clients.google_client",
            side_effect=Exception("API down"),
        ):
            result = await restructure_observations(obs)
        assert result == obs

    async def test_empty_returns_empty(self):
        result = await restructure_observations([])
        assert result == []


# ---------------------------------------------------------------------------
# load_user_observations
# ---------------------------------------------------------------------------
class TestLoadUserObservations:
    async def test_returns_observations(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {
            "observations": ["[2026-03-01] Pattern A"]
        }
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            result = await load_user_observations("00000000-0000-0000-0000-000000000001")
        assert result == ["[2026-03-01] Pattern A"]

    async def test_no_profile_returns_empty(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            result = await load_user_observations("00000000-0000-0000-0000-000000000001")
        assert result == []

    async def test_no_observations_key_returns_empty(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {"personality": {}}
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            result = await load_user_observations("00000000-0000-0000-0000-000000000001")
        assert result == []

    async def test_db_failure_returns_empty(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            result = await load_user_observations("00000000-0000-0000-0000-000000000001")
        assert result == []


# ---------------------------------------------------------------------------
# save_user_observations
# ---------------------------------------------------------------------------
class TestSaveUserObservations:
    async def test_saves_to_profile(self):
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {"personality": {}}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        obs = ["[2026-03-01] Pattern A"]

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            await save_user_observations(uid, obs)

        assert mock_profile.learned_patterns["observations"] == obs
        mock_session.commit.assert_called_once()

    async def test_caps_at_max_stored(self):
        mock_profile = MagicMock()
        mock_profile.learned_patterns = {}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        obs = [f"[2026-03-01] Obs {i}" for i in range(100)]

        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            await save_user_observations(uid, obs)

        saved = mock_profile.learned_patterns["observations"]
        assert len(saved) == MAX_STORED_OBSERVATIONS

    async def test_no_profile_graceful(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        uid = "00000000-0000-0000-0000-000000000001"
        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            # Should not raise
            await save_user_observations(uid, ["obs"])
        mock_session.commit.assert_not_called()

    async def test_db_failure_graceful(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        uid = "00000000-0000-0000-0000-000000000001"
        with patch(
            "src.core.db.async_session",
            return_value=mock_ctx,
        ):
            # Should not raise
            await save_user_observations(uid, ["obs"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_observer_threshold(self):
        assert OBSERVER_TOKEN_THRESHOLD == 25_000

    def test_reflector_threshold(self):
        assert REFLECTOR_TOKEN_THRESHOLD == 30_000

    def test_max_stored(self):
        assert MAX_STORED_OBSERVATIONS == 50

    def test_observation_intents(self):
        assert "complex_query" in OBSERVATION_INTENTS
        assert "financial_summary" in OBSERVATION_INTENTS
        assert "morning_brief" in OBSERVATION_INTENTS
        assert "add_expense" not in OBSERVATION_INTENTS
