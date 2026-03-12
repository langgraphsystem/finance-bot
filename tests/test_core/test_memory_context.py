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

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.memory.context import (
    BUDGET_RATIO,
    MAX_CONTEXT_TOKENS,
    QUERY_CONTEXT_MAP,
    AssembledContext,
    _apply_overflow_trimming,
    _format_memories_block,
    _format_sql_block,
    _load_sql_stats,
    _resolve_sql_period,
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

    def test_prefers_explicit_critical_memories_when_budget_is_tight(self):
        memories = [
            {
                "memory": "older low-priority filler",
                "metadata": {"priority": "normal", "write_policy": "implicit"},
                "score": 0.9,
            },
            {
                "memory": "critical explicit fact",
                "metadata": {
                    "priority": "critical",
                    "write_policy": "explicit",
                    "confidence": 1.0,
                },
                "score": 0.5,
            },
        ]

        result = _trim_memories(memories, 14)

        assert len(result) == 1
        assert result[0]["memory"] == "critical explicit fact"


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

    def test_uses_period_label_and_previous_label(self):
        stats = {
            "period_label": "эту неделю",
            "month_start": "2026-02-01",
            "total_expense": 500.0,
            "total_income": 700.0,
            "previous_expense": 400.0,
            "previous_label": "предыдущую неделю",
            "by_category": [],
        }
        result = _format_sql_block(stats)
        assert "Эту неделю:" in result
        assert "Предыдущую неделю расходы" in result


class TestResolveSqlPeriod:
    def test_query_stats_week(self):
        start, end, label = _resolve_sql_period("query_stats", {"period": "week"})
        assert start <= end
        assert label == "эту неделю"

    def test_query_report_explicit_month(self):
        start, end, label = _resolve_sql_period(
            "query_report",
            {"date": "2026-01-15"},
        )
        assert start == date(2026, 1, 1)
        assert end == date(2026, 2, 1)
        assert label == "2026-01"


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

    def test_general_chat_profile_mem(self):
        cfg = QUERY_CONTEXT_MAP["general_chat"]
        assert cfg["mem"] == "profile"
        assert cfg["hist"] == 0
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

    def test_scan_document_exists(self):
        assert "scan_document" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["scan_document"]
        assert cfg["mem"] == "mappings"
        assert cfg["hist"] == 1

    def test_set_budget_exists(self):
        assert "set_budget" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["set_budget"]
        assert cfg["mem"] == "budgets"
        assert cfg["sql"] is True

    def test_mark_paid_exists(self):
        assert "mark_paid" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["mark_paid"]
        assert cfg["mem"] is False
        assert cfg["hist"] == 3

    def test_add_recurring_exists(self):
        assert "add_recurring" in QUERY_CONTEXT_MAP
        cfg = QUERY_CONTEXT_MAP["add_recurring"]
        assert cfg["mem"] == "mappings"

    def test_no_dead_entries(self):
        assert "budget_advice" not in QUERY_CONTEXT_MAP
        assert "correct_cat" not in QUERY_CONTEXT_MAP

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
    def _unpack(self, result):
        """Unpack 9-tuple from _apply_overflow_trimming."""
        (
            mem_block, sql_block, summary_block, history, memories,
            obs_block, proc_block, ep_block, graph_block,
        ) = result
        return mem_block, sql_block, summary_block, history, memories

    def test_no_trimming_when_within_budget(self):
        result = _apply_overflow_trimming(
            system_prompt_tokens=10,
            user_msg_tokens=5,
            mem_block="mem",
            sql_block="sql",
            summary_block="sum",
            history_messages=[],
            memories=[{"memory": "test"}],
            total_budget=10000,
        )
        mem_block, sql_block, summary_block, history, memories = self._unpack(result)
        assert mem_block == "mem"
        assert sql_block == "sql"
        assert summary_block == "sum"

    def test_drops_old_history_first(self):
        # Large history to trigger overflow
        history = [{"role": "user", "content": "x" * 400} for _ in range(10)]
        result = _apply_overflow_trimming(
            system_prompt_tokens=10,
            user_msg_tokens=5,
            mem_block="",
            sql_block="",
            summary_block="",
            history_messages=history,
            memories=[],
            total_budget=500,  # tight budget
        )
        _, _, _, trimmed_history, _ = self._unpack(result)
        # Should have fewer messages
        assert len(trimmed_history) < 10

    def test_drops_summary_before_sql(self):
        # Budget tight enough that summary should be compressed
        history = []
        summary = "s" * 2000
        sql = "q" * 100
        result = _apply_overflow_trimming(
            system_prompt_tokens=10,
            user_msg_tokens=5,
            mem_block="",
            sql_block=sql,
            summary_block=summary,
            history_messages=history,
            memories=[],
            total_budget=100,  # very tight
        )
        _, _, summary_block, _, _ = self._unpack(result)
        # Summary should be trimmed or empty
        assert len(summary_block) < len(summary)

    def test_never_drops_system_and_user(self):
        # Even with extremely tight budget, we should not crash
        result = _apply_overflow_trimming(
            system_prompt_tokens=50,
            user_msg_tokens=50,
            mem_block="m" * 1000,
            sql_block="s" * 1000,
            summary_block="u" * 1000,
            history_messages=[{"role": "user", "content": "x" * 500} for _ in range(10)],
            memories=[{"memory": "test"}],
            total_budget=100,  # exactly system + user, no room for anything else
        )
        mem_block, sql_block, summary_block, history, memories = self._unpack(result)
        # Everything else should be trimmed away
        assert len(history) == 0
        assert summary_block == ""
        assert sql_block == ""
        assert mem_block == ""
        assert memories == []

    def test_drops_episodes_and_graph_before_mem0(self):
        """Episodic and graph blocks should be dropped before Mem0 and SQL."""
        result = _apply_overflow_trimming(
            system_prompt_tokens=10,
            user_msg_tokens=5,
            mem_block="mem data",
            sql_block="sql data",
            summary_block="",
            history_messages=[],
            memories=[{"memory": "test"}],
            total_budget=50,  # tight — forces auxiliary drops
            episodes_block="e" * 200,
            graph_block="g" * 200,
            observations_block="o" * 200,
        )
        (
            mem_block, sql_block, _, _, _,
            obs_block, _, ep_block, graph_block,
        ) = result
        # Auxiliary layers should be dropped first
        assert ep_block == ""
        assert graph_block == ""


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
            patch(
                "src.core.identity.get_core_identity",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "src.core.memory.session_buffer.get_session_buffer",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.core.memory.observational.load_user_observations",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.core.memory.procedural.get_procedures",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_sw.get_recent_messages = AsyncMock(return_value=[])
            mock_mem0.search_memories = AsyncMock(return_value=[])
            mock_mem0.search_memories_multi_domain = AsyncMock(return_value=[])
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
        assert result.context_config
        assert result.requested_context_config

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
        """general_chat with simple input skips Mem0 (progressive disclosure)."""
        await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hi",
            intent="general_chat",
            system_prompt="prompt",
        )
        mock_deps["mem0"].search_memories.assert_not_called()
        mock_deps["mem0"].search_memories_multi_domain.assert_not_called()
        mock_deps["mem0"].get_all_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_override_can_restore_history_for_general_chat(self, mock_deps):
        mock_deps["sliding_window"].get_recent_messages.return_value = [
            {"role": "assistant", "content": "previous reply"},
        ]

        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hello again",
            intent="general_chat",
            system_prompt="prompt",
            context_config_override={"hist": 1, "mem": False, "sql": False, "sum": False},
        )

        assert result.context_config["hist"] == 1
        assert len(result.messages) == 3

    @pytest.mark.asyncio
    async def test_add_expense_loads_mappings(self, mock_deps):
        mock_deps["mem0"].search_memories_multi_domain.return_value = [
            {"memory": "Shell -> Diesel"}
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="заправился на 50",
            intent="add_expense",
            system_prompt="prompt",
        )
        # With domain segmentation, uses multi_domain search
        mock_deps["mem0"].search_memories_multi_domain.assert_called_once()
        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_session_buffer_suppresses_conflicting_mem0_and_traces_it(self, mock_deps):
        mock_deps["mem0"].search_memories_multi_domain.return_value = [
            {
                "id": "mem-old-income",
                "memory": "Salary is 5000",
                "metadata": {"category": "income", "domain": "finance", "source": "mem0"},
                "score": 0.95,
            },
            {
                "id": "mem-budget",
                "memory": "Budget for groceries is 1200",
                "metadata": {"category": "budget_limit", "domain": "finance"},
                "score": 0.8,
            },
        ]

        with patch(
            "src.core.memory.session_buffer.get_session_buffer",
            new_callable=AsyncMock,
            return_value=[
                {
                    "fact": "Salary is now 6000",
                    "category": "income",
                    "domain": "finance",
                }
            ],
        ):
            result = await assemble_context(
                user_id="user-1",
                family_id="family-1",
                current_message="compare my salary and grocery budget",
                intent="complex_query",
                system_prompt="prompt",
                context_config_override={"sql": False, "sum": False, "hist": 0},
            )

        memory_ids = {item.get("id") for item in result.memories}
        assert "mem-old-income" not in memory_ids
        assert "mem-budget" in memory_ids

        suppressed = [
            entry for entry in result.memory_trace
            if entry.get("layer") == "mem0" and entry.get("status") == "suppressed"
        ]
        assert any(
            entry.get("id") == "mem-old-income"
            and entry.get("reason") == "overridden_by_session_buffer"
            and entry.get("overridden_by") == "session_buffer"
            for entry in suppressed
        )

        session_entries = [
            entry for entry in result.memory_trace
            if entry.get("layer") == "session_buffer" and entry.get("status") == "selected"
        ]
        assert session_entries
        assert session_entries[0]["precedence"] < suppressed[0]["precedence"]

    @pytest.mark.asyncio
    async def test_unknown_intent_falls_back_to_general_chat(self, mock_deps):
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="test",
            intent="unknown_intent_xyz",
            system_prompt="prompt",
        )
        # Should still work without error (falls back to general_chat config)
        assert isinstance(result, AssembledContext)

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
    async def test_query_stats_includes_history(self, mock_deps):
        """query_stats has hist=3 for follow-up context."""
        mock_deps["sliding_window"].get_recent_messages.return_value = [
            {"role": "user", "content": "show budget"},
            {"role": "assistant", "content": "Your budget is 1000"},
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="stats",
            intent="query_stats",
            system_prompt="prompt",
        )
        mock_deps["sliding_window"].get_recent_messages.assert_called_once()
        # system + 2 history + user
        assert len(result.messages) == 4

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
        mock_deps["mem0"].search_memories_multi_domain.return_value = [
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
            {"role": "user", "content": "x" * 200} for _ in range(10)
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
        mock_deps["mem0"].search_memories_multi_domain.return_value = [
            {"memory": "currency: USD"},
        ]
        result = await assemble_context(
            user_id="user-1",
            family_id="family-1",
            current_message="hi",
            intent="onboarding",
            system_prompt="prompt",
        )
        # Domain segmentation: onboarding falls back to profile→[core, finance]
        mock_deps["mem0"].search_memories_multi_domain.assert_called_once()
        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_mem0_failure_graceful(self, mock_deps):
        """If Mem0 raises, context assembly should still succeed."""
        mock_deps["mem0"].search_memories_multi_domain.side_effect = Exception("Mem0 down")
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
        mock_deps["sliding_window"].get_recent_messages.side_effect = Exception("Redis down")
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
        """query_stats should use domain-scoped search for finance."""
        mock_deps["mem0"].search_memories_multi_domain.return_value = [
            {"memory": "budget limit 50000"}
        ]
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
        # Domain segmentation: query_stats → [finance, core]
        mock_deps["mem0"].search_memories_multi_domain.assert_called_once()
        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_sql_loader_receives_role_and_intent_data(self, mock_deps):
        with patch(
            "src.core.memory.context._load_sql_stats",
            new_callable=AsyncMock,
            return_value={
                "period_label": "эту неделю",
                "month_start": "2026-02-01",
                "total_expense": 0,
                "total_income": 0,
                "by_category": [],
                "previous_expense": 0,
                "previous_label": "предыдущую неделю",
            },
        ) as mock_sql:
            await assemble_context(
                user_id="user-1",
                family_id="family-1",
                current_message="покажи статистику за неделю",
                intent="query_stats",
                system_prompt="prompt",
                role="member",
                intent_data={"period": "week"},
            )

        mock_sql.assert_awaited_once_with(
            "family-1",
            role="member",
            user_id="user-1",
            intent="query_stats",
            intent_data={"period": "week"},
        )


class TestLoadSqlStats:
    @pytest.mark.asyncio
    async def test_applies_visibility_filter_and_period(self):
        expense_result = MagicMock()
        expense_result.all.return_value = [
            (None, Decimal("125"), 2),
        ]
        income_result = MagicMock()
        income_result.scalar.return_value = Decimal("300")
        prev_result = MagicMock()
        prev_result.scalar.return_value = Decimal("80")

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[expense_result, income_result, prev_result]
        )
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.core.db.async_session",
                return_value=ctx,
            ),
            patch(
                "src.core.access.apply_visibility_filter",
                side_effect=lambda stmt, model, role, user_id: stmt,
            ) as mock_filter,
        ):
            stats = await _load_sql_stats(
                str(uuid.uuid4()),
                role="member",
                user_id=str(uuid.uuid4()),
                intent="query_stats",
                intent_data={"period": "week"},
            )

        assert stats["period_label"] == "эту неделю"
        assert stats["by_category"][0]["name"] == "Без категории"
        assert stats["total_expense"] == 125.0
        assert stats["total_income"] == 300.0
        assert stats["previous_expense"] == 80.0
        assert mock_filter.call_count == 3
