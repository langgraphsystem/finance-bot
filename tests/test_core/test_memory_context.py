"""Tests for context assembly with token budget management (Phase 2).

Tests cover:
- count_tokens helper
- _truncate_to_budget helper
- _trim_memories helper
- QUERY_CONTEXT_MAP configuration
- assemble_context budget enforcement
- Overflow priority trimming
- Lost-in-the-Middle positioning
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.core.memory.context import (
    QUERY_CONTEXT_MAP,
    AssembledContext,
    BUDGET_RATIO,
    MAX_CONTEXT_TOKENS,
    MIN_SLIDING_WINDOW,
    _apply_overflow_trimming,
    _format_memories_block,
    _format_sql_block,
    _trim_memories,
    _truncate_to_budget,
    assemble_context,
    count_tokens,
)


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------
class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 1  # len("") // 4 + 1

    def test_short_english(self):
        # "hello" = 5 chars -> 5 // 4 + 1 = 2
        assert count_tokens("hello") == 2

    def test_longer_text(self):
        text = "a" * 100  # 100 chars -> 100 // 4 + 1 = 26
        assert count_tokens(text) == 26

    def test_russian_text(self):
        text = "Привет мир"  # each Cyrillic char is 2 bytes but len() counts chars
        result = count_tokens(text)
        assert result == len(text) // 4 + 1

    def test_always_positive(self):
        assert count_tokens("") >= 1
        assert count_tokens("a") >= 1


# ---------------------------------------------------------------------------
# _truncate_to_budget
# ---------------------------------------------------------------------------
class TestTruncateToBudget:
    def test_no_truncation_if_within_budget(self):
        text = "short text"
        result = _truncate_to_budget(text, 100)
        assert result == text

    def test_truncation_adds_marker(self):
        text = "a" * 1000
        result = _truncate_to_budget(text, 10)
        assert result.endswith("\n...[обрезано]")
        # The truncated part should be shorter than the original
        assert len(result) < len(text)

    def test_zero_budget(self):
        result = _truncate_to_budget("some text", 0)
        assert result.endswith("\n...[обрезано]")

    def test_exact_boundary(self):
        # 10 tokens * 4 chars = budget allows 36 chars ((10-1)*4 = 36)
        text = "a" * 36
        result = _truncate_to_budget(text, 10)
        assert result == text  # fits exactly


# ---------------------------------------------------------------------------
# _trim_memories
# ---------------------------------------------------------------------------
class TestTrimMemories:
    def test_empty_list(self):
        assert _trim_memories([], 100) == []

    def test_all_fit(self):
        memories = [
            {"memory": "fact 1"},
            {"memory": "fact 2"},
        ]
        result = _trim_memories(memories, 1000)
        assert len(result) == 2

    def test_trims_to_budget(self):
        # Create memories that are large enough to exceed a small budget
        memories = [{"memory": "x" * 100} for _ in range(20)]
        result = _trim_memories(memories, 50)
        assert len(result) < 20

    def test_keeps_order(self):
        memories = [
            {"memory": "first"},
            {"memory": "second"},
            {"memory": "third"},
        ]
        result = _trim_memories(memories, 1000)
        assert result[0]["memory"] == "first"
        assert result[-1]["memory"] == "third"

    def test_uses_text_fallback(self):
        memories = [{"text": "fallback text"}]
        result = _trim_memories(memories, 1000)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _format_memories_block
# ---------------------------------------------------------------------------
class TestFormatMemoriesBlock:
    def test_empty_returns_empty(self):
        assert _format_memories_block([]) == ""

    def test_formats_correctly(self):
        memories = [{"memory": "fact 1"}, {"memory": "fact 2"}]
        result = _format_memories_block(memories)
        assert "## Что я знаю о вас:" in result
        assert "- fact 1" in result
        assert "- fact 2" in result


# ---------------------------------------------------------------------------
# _format_sql_block
# ---------------------------------------------------------------------------
class TestFormatSqlBlock:
    def test_formats_basic_stats(self):
        stats = {
            "month_start": "2026-02-01",
            "total_expense": 1500.0,
            "total_income": 3000.0,
            "prev_month_expense": 0,
            "by_category": [],
        }
        result = _format_sql_block(stats)
        assert "Текущий месяц" in result
        assert "$1500.00" in result
        assert "$3000.00" in result

    def test_includes_categories(self):
        stats = {
            "month_start": "2026-02-01",
            "total_expense": 1000.0,
            "total_income": 2000.0,
            "prev_month_expense": 0,
            "by_category": [
                {"name": "Продукты", "total": 500.0, "count": 10},
                {"name": "Транспорт", "total": 300.0, "count": 5},
            ],
        }
        result = _format_sql_block(stats)
        assert "Продукты" in result
        assert "Транспорт" in result


# ---------------------------------------------------------------------------
# QUERY_CONTEXT_MAP
# ---------------------------------------------------------------------------
class TestQueryContextMap:
    def test_all_intents_have_required_keys(self):
        required_keys = {"mem", "hist", "sql", "sum"}
        for intent, config in QUERY_CONTEXT_MAP.items():
            assert required_keys.issubset(config.keys()), (
                f"Intent '{intent}' missing keys: {required_keys - config.keys()}"
            )

    def test_add_expense_config(self):
        cfg = QUERY_CONTEXT_MAP["add_expense"]
        assert cfg["mem"] == "mappings"
        assert cfg["hist"] == 3
        assert cfg["sql"] is False
        assert cfg["sum"] is False

    def test_complex_query_loads_everything(self):
        cfg = QUERY_CONTEXT_MAP["complex_query"]
        assert cfg["mem"] == "all"
        assert cfg["sql"] is True
        assert cfg["sum"] is True

    def test_general_chat_no_mem(self):
        cfg = QUERY_CONTEXT_MAP["general_chat"]
        assert cfg["mem"] is False
        assert cfg["sql"] is False

    def test_undo_last_exists(self):
        assert "undo_last" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["undo_last"]
        assert cfg["mem"] is False
        assert cfg["hist"] == 5

    def test_correct_category_exists(self):
        assert "correct_category" in QUERY_CONTEXT_MAP

    def test_scan_receipt_exists(self):
        assert "scan_receipt" in QUERY_CONTEXT_MAP

    def test_budget_advice_exists(self):
        assert "budget_advice" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["budget_advice"]
        assert cfg["sql"] is True
        assert cfg["sum"] is True

    def test_query_report_exists(self):
        assert "query_report" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["query_report"]
        assert cfg["mem"] == "profile"
        assert cfg["sql"] is True

    def test_query_stats_uses_budgets_mem(self):
        cfg = QUERY_CONTEXT_MAP["query_stats"]
        assert cfg["mem"] == "budgets"

    def test_onboarding_high_history(self):
        cfg = QUERY_CONTEXT_MAP["onboarding"]
        assert cfg["hist"] == 10
        assert cfg["mem"] == "profile"


# ---------------------------------------------------------------------------
# _apply_overflow_trimming
# ---------------------------------------------------------------------------
class TestOverflowTrimming:
    def test_no_trimming_when_within_budget(self):
        mem_block, sql_block, summary_block, history, memories = (
            _apply_overflow_trimming(
                system_prompt_tokens=10,
                user_msg_tokens=5,
                mem_block="mem",
                sql_block="sql",
                summary_block="sum",
                history_messages=[],
                memories=[{"memory": "test"}],
                total_budget=10000,
            )
        )
        assert mem_block == "mem"
        assert sql_block == "sql"
        assert summary_block == "sum"

    def test_drops_old_history_first(self):
        # Large history to trigger overflow
        history = [
            {"role": "user", "content": "x" * 400}
            for _ in range(10)
        ]
        mem_block, sql_block, summary_block, trimmed_history, memories = (
            _apply_overflow_trimming(
                system_prompt_tokens=10,
                user_msg_tokens=5,
                mem_block="",
                sql_block="",
                summary_block="",
                history_messages=history,
                memories=[],
                total_budget=500,  # tight budget
            )
        )
        # Should have fewer messages
        assert len(trimmed_history) < 10

    def test_drops_summary_before_sql(self):
        # Budget tight enough that summary should be compressed
        history = []
        summary = "s" * 2000
        sql = "q" * 100
        mem_block, sql_block, summary_block, _, _ = _apply_overflow_trimming(
            system_prompt_tokens=10,
            user_msg_tokens=5,
            mem_block="",
            sql_block=sql,
            summary_block=summary,
            history_messages=history,
            memories=[],
            total_budget=100,  # very tight
        )
        # Summary should be trimmed or empty
        assert len(summary_block) < len(summary)

    def test_never_drops_system_and_user(self):
        # Even with extremely tight budget, we should not crash
        mem_block, sql_block, summary_block, history, memories = (
            _apply_overflow_trimming(
                system_prompt_tokens=50,
                user_msg_tokens=50,
                mem_block="m" * 1000,
                sql_block="s" * 1000,
                summary_block="u" * 1000,
                history_messages=[
                    {"role": "user", "content": "x" * 500}
                    for _ in range(10)
                ],
                memories=[{"memory": "test"}],
                total_budget=100,  # exactly system + user, no room for anything else
            )
        )
        # Everything else should be trimmed away
        assert len(history) == 0
        assert summary_block == ""
        assert sql_block == ""
        assert mem_block == ""
        assert memories == []


# ---------------------------------------------------------------------------
# assemble_context (integration tests with mocks)
# ---------------------------------------------------------------------------
class TestAssembleContext:
    @pytest.fixture
    def mock_deps(self):
        """Mock all external dependencies for assemble_context."""
        with (
            patch("src.core.memory.context.sliding_window") as mock_sw,
            patch("src.core.memory.context.mem0_client") as mock_mem0,
            patch("src.core.memory.context.get_session_summary") as mock_summary,
            patch("src.core.memory.context.observe", lambda **kw: lambda fn: fn),
        ):
            mock_sw.get_recent_messages = AsyncMock(return_value=[])
            mock_mem0.search_memories = AsyncMock(return_value=[])
            mock_mem0.get_all_memories = AsyncMock(return_value=[])
            mock_summary.return_value = None
            yield {
                "sliding_window": mock_sw,
                "mem0": mock_mem0,
                "summary": mock_summary,
            }

    @pytest.mark.asyncio
    async def test_basic_assembly(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hello",
            intent="general_chat",
            system_prompt="You are a bot.",
        )
        assert isinstance(result, AssembledContext)
        assert result.system_prompt == "You are a bot."
        assert len(result.messages) >= 2  # system + user
        assert result.messages[0]["role"] == "system"
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_token_usage_tracked(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="general_chat",
            system_prompt="prompt",
        )
        assert "total" in result.token_usage
        assert "budget" in result.token_usage
        assert "system_prompt" in result.token_usage
        assert "user_message" in result.token_usage

    @pytest.mark.asyncio
    async def test_budget_respected(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="general_chat",
            system_prompt="prompt",
            max_tokens=200_000,
        )
        budget = int(200_000 * BUDGET_RATIO)
        assert result.token_usage["total"] <= budget

    @pytest.mark.asyncio
    async def test_general_chat_no_mem0_call(self, mock_deps):
        """general_chat has mem=False, so Mem0 should not be called."""
        await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hi",
            intent="general_chat",
            system_prompt="prompt",
        )
        mock_deps["mem0"].search_memories.assert_not_called()
        mock_deps["mem0"].get_all_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_expense_loads_mappings(self, mock_deps):
        mock_deps["mem0"].search_memories.return_value = [
            {"memory": "Shell -> Diesel"}
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="заправился на 50",
            intent="add_expense",
            system_prompt="prompt",
        )
        mock_deps["mem0"].search_memories.assert_called_once()
        call_kwargs = mock_deps["mem0"].search_memories.call_args
        assert call_kwargs[1].get("filters") == {"category": "merchant_mapping"}
        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_unknown_intent_falls_back_to_general_chat(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="unknown_intent_xyz",
            system_prompt="prompt",
        )
        # Should still work without error (falls back to general_chat)
        assert isinstance(result, AssembledContext)
        # general_chat has mem=False, so no mem0 calls
        mock_deps["mem0"].search_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_history_included_for_add_expense(self, mock_deps):
        mock_deps["sliding_window"].get_recent_messages.return_value = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="заправился",
            intent="add_expense",
            system_prompt="prompt",
        )
        # system + 3 history + current = 5
        assert len(result.messages) == 5

    @pytest.mark.asyncio
    async def test_no_history_for_query_stats(self, mock_deps):
        """query_stats has hist=0."""
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="stats",
            intent="query_stats",
            system_prompt="prompt",
        )
        mock_deps["sliding_window"].get_recent_messages.assert_not_called()
        # Only system + user
        assert len(result.messages) == 2

    @pytest.mark.asyncio
    async def test_lost_in_middle_system_first_user_last(self, mock_deps):
        mock_deps["sliding_window"].get_recent_messages.return_value = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "response"},
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="current",
            intent="general_chat",
            system_prompt="system",
        )
        assert result.messages[0]["role"] == "system"
        assert result.messages[-1]["role"] == "user"
        assert result.messages[-1]["content"] == "current"

    @pytest.mark.asyncio
    async def test_lost_in_middle_mem_at_end_of_system(self, mock_deps):
        """Mem0 block should be at the END of the system prompt
        (closer to recent messages = higher attention)."""
        mock_deps["mem0"].search_memories.return_value = [
            {"memory": "user likes cats"}
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="add_expense",
            system_prompt="You are a finance bot.",
        )
        system_content = result.messages[0]["content"]
        # Mem block should come after the base system prompt
        base_idx = system_content.find("You are a finance bot.")
        mem_idx = system_content.find("Что я знаю о вас:")
        assert mem_idx > base_idx

    @pytest.mark.asyncio
    async def test_tight_budget_trims_content(self, mock_deps):
        """With a very small max_tokens, content should be trimmed."""
        mock_deps["sliding_window"].get_recent_messages.return_value = [
            {"role": "user", "content": "x" * 200}
            for _ in range(10)
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="general_chat",
            system_prompt="prompt",
            max_tokens=200,  # very tight
        )
        budget = int(200 * BUDGET_RATIO)
        assert result.token_usage["total"] <= budget

    @pytest.mark.asyncio
    async def test_max_tokens_default(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="general_chat",
            system_prompt="prompt",
        )
        assert result.token_usage["budget"] == int(MAX_CONTEXT_TOKENS * BUDGET_RATIO)

    @pytest.mark.asyncio
    async def test_onboarding_loads_profile_memories(self, mock_deps):
        mock_deps["mem0"].get_all_memories.return_value = [
            {"memory": "currency: USD"},
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hi",
            intent="onboarding",
            system_prompt="prompt",
        )
        mock_deps["mem0"].get_all_memories.assert_called_once_with("user-1")
        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_mem0_failure_graceful(self, mock_deps):
        """If Mem0 raises, context assembly should still succeed."""
        mock_deps["mem0"].search_memories.side_effect = Exception("Mem0 down")
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="add_expense",
            system_prompt="prompt",
        )
        assert isinstance(result, AssembledContext)
        assert result.memories == []

    @pytest.mark.asyncio
    async def test_sliding_window_failure_graceful(self, mock_deps):
        """If Redis is down, context assembly should still succeed."""
        mock_deps["sliding_window"].get_recent_messages.side_effect = Exception(
            "Redis down"
        )
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="general_chat",
            system_prompt="prompt",
        )
        assert isinstance(result, AssembledContext)
        # Should have system + user only
        assert len(result.messages) == 2

    @pytest.mark.asyncio
    async def test_query_stats_loads_budgets_mem(self, mock_deps):
        """query_stats should use 'budgets' mem type."""
        mock_deps["mem0"].search_memories.return_value = [
            {"memory": "budget limit 50000"}
        ]
        # Also need to mock _load_sql_stats since query_stats has sql=True
        with patch(
            "src.core.memory.context._load_sql_stats",
            new_callable=AsyncMock,
            return_value={
                "period": "current_month",
                "month_start": "2026-02-01",
                "total_expense": 0,
                "total_income": 0,
                "by_category": [],
                "prev_month_expense": 0,
            },
        ):
            result = await assemble_context(
                user_id="user-1",
                family_id="family-1",
                current_message="stats",
                intent="query_stats",
                system_prompt="prompt",
            )
        # Should have called search_memories with budget query
        mock_deps["mem0"].search_memories.assert_called_once()
        call_args = mock_deps["mem0"].search_memories.call_args
        assert call_args[0][0] == "budget limits goals"
