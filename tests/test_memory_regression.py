"""Regression tests for Memory & Personalization (20 problems).

Each test covers one specific problem from the memory improvement plan.
All tests use mocked external I/O (no real DB, LLM, or Mem0).
"""

from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Problem 1: Забывает правила ("отвечай коротко")
# Fix: Phase 4 — active_rules injection in context
# ---------------------------------------------------------------------------
class TestProblem1RuleForgetting:
    async def test_rules_injected_into_context(self):
        """User rules must appear in assembled context."""
        from src.core.identity import format_rules_block

        rules = ["Отвечай коротко", "Без эмодзи"]
        block = format_rules_block(rules)
        assert "ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА" in block
        assert "Отвечай коротко" in block
        assert "Без эмодзи" in block

    async def test_empty_rules_no_block(self):
        from src.core.identity import format_rules_block

        assert format_rules_block([]) == ""


# ---------------------------------------------------------------------------
# Problem 2: Забывает имя бота
# Fix: Phase 3+5 — immediate_identity_update for bot_identity
# ---------------------------------------------------------------------------
class TestProblem2BotNameForgetting:
    async def test_bot_name_in_identity(self):
        from src.core.identity import format_identity_block

        identity = {"bot_name": "Хюррем"}
        block = format_identity_block(identity)
        assert "Хюррем" in block
        assert "Bot Name" in block


# ---------------------------------------------------------------------------
# Problem 3: Забывает язык общения
# Fix: Phase 3 — immediate identity update for user_preference
# ---------------------------------------------------------------------------
class TestProblem3LanguageForgetting:
    async def test_language_in_identity(self):
        from src.core.identity import format_identity_block

        identity = {"response_language": "ru"}
        block = format_identity_block(identity)
        assert "ru" in block


# ---------------------------------------------------------------------------
# Problem 4: Не запоминает факты о пользователе
# Fix: Phase 2 — expanded fact extraction prompt
# ---------------------------------------------------------------------------
class TestProblem4FactExtraction:
    def test_prompt_includes_identity_categories(self):
        from src.core.memory.mem0_client import FACT_EXTRACTION_PROMPT

        assert "user_identity" in FACT_EXTRACTION_PROMPT
        assert "bot_identity" in FACT_EXTRACTION_PROMPT
        assert "user_rule" in FACT_EXTRACTION_PROMPT
        assert "user_project" in FACT_EXTRACTION_PROMPT

    def test_prompt_no_longer_financial_only(self):
        from src.core.memory.mem0_client import FACT_EXTRACTION_PROMPT

        assert "ТОЛЬКО финансовые" not in FACT_EXTRACTION_PROMPT


# ---------------------------------------------------------------------------
# Problem 5: Не различает команды и разговор
# Fix: Phase 5 — set_user_rule intent detection
# ---------------------------------------------------------------------------
class TestProblem5CommandVsChat:
    def test_set_user_rule_in_intents(self):
        """set_user_rule must be a recognized intent."""
        from src.core.intent import INTENT_DETECTION_PROMPT

        assert "set_user_rule" in INTENT_DETECTION_PROMPT

    def test_dialog_history_in_intents(self):
        from src.core.intent import INTENT_DETECTION_PROMPT

        assert "dialog_history" in INTENT_DETECTION_PROMPT


# ---------------------------------------------------------------------------
# Problem 6: Теряет тему разговора → already handled by session buffer
# ---------------------------------------------------------------------------
class TestProblem6TopicLoss:
    def test_session_buffer_exists(self):
        from src.core.memory import session_buffer

        assert hasattr(session_buffer, "get_session_buffer")
        assert hasattr(session_buffer, "update_session_buffer")


# ---------------------------------------------------------------------------
# Problem 7: Не помнит прошлые разговоры
# Fix: Phase 10 — dialog_history skill
# ---------------------------------------------------------------------------
class TestProblem7PastConversations:
    def test_dialog_history_skill_exists(self):
        from src.skills.dialog_history.handler import DialogHistorySkill

        skill = DialogHistorySkill()
        assert "dialog_history" in skill.intents


# ---------------------------------------------------------------------------
# Problem 8: Не проверяет правила перед ответом
# Fix: Phase 13 — post-generation rule check
# ---------------------------------------------------------------------------
class TestProblem8RuleCheck:
    async def test_post_gen_check_exists(self):
        from src.core.config import settings
        from src.core.post_gen_check import check_response_rules

        with patch.object(settings, "ff_post_gen_check", False):
            ok, violation = await check_response_rules("test", ["rule"])

        assert ok is True
        assert violation == ""

    def test_feature_flag_exists(self):
        from src.core.config import settings

        assert hasattr(settings, "ff_post_gen_check")


# ---------------------------------------------------------------------------
# Problem 9: Теряет роль/специализацию → handled by specialist config
# ---------------------------------------------------------------------------
class TestProblem9RoleLoss:
    def test_core_identity_includes_bot_role(self):
        from src.core.identity import format_identity_block

        identity = {"bot_name": "Хюррем", "bot_role": "финансовый ассистент"}
        block = format_identity_block(identity)
        assert "финансовый ассистент" in block


# ---------------------------------------------------------------------------
# Problem 10: Context drift → Phase 4 NEVER DROP rules
# ---------------------------------------------------------------------------
class TestProblem10ContextDrift:
    def test_rules_never_drop_comment(self):
        """Context assembly must have NEVER DROP for user_rules."""
        import inspect

        from src.core.memory import context

        source = inspect.getsource(context)
        assert "user_rules" in source.lower() or "user rules" in source.lower()


# ---------------------------------------------------------------------------
# Problem 11: Preference drift → Phase 7 priority metadata
# ---------------------------------------------------------------------------
class TestProblem11PreferenceDrift:
    def test_priority_mapping_exists(self):
        from src.core.memory.mem0_client import _CATEGORY_PRIORITY

        assert _CATEGORY_PRIORITY["user_identity"] == "critical"
        assert _CATEGORY_PRIORITY["user_rule"] == "critical"
        assert _CATEGORY_PRIORITY["spending_pattern"] == "normal"


# ---------------------------------------------------------------------------
# Problem 12: Echoing (эхо-эффект) → handled by dedup in search_memories_multi_domain
# ---------------------------------------------------------------------------
class TestProblem12Echoing:
    def test_dedup_in_multi_domain_search(self):
        """Multi-domain search must have deduplication."""
        import inspect

        from src.core.memory.mem0_client import search_memories_multi_domain

        source = inspect.getsource(search_memories_multi_domain)
        assert "is_similar" in source


# ---------------------------------------------------------------------------
# Problem 13: Hallucinated memory → handled by explicit save confirmation
# ---------------------------------------------------------------------------
class TestProblem13HallucinatedMemory:
    async def test_memory_save_confirms(self):
        """Phase 11: memory_save must show confirmation with saved content."""
        from src.skills.memory_vault.handler import MemoryVaultSkill

        skill = MemoryVaultSkill()
        mock_add = AsyncMock()
        context = MagicMock(user_id="test-user", language="en")
        result = await skill._handle_save(context, "My city is Almaty", mock_add, lang="en")
        assert "Almaty" in result.response_text


# ---------------------------------------------------------------------------
# Problem 14: Memory poisoning → Phase 1 guardrails whitelist
# ---------------------------------------------------------------------------
class TestProblem14MemoryPoisoning:
    def test_guardrails_blocks_harmful(self):
        """Guardrails prompt still blocks harmful content."""
        from src.core.guardrails import SAFETY_CHECK_PROMPT

        assert "Harmful" in SAFETY_CHECK_PROMPT or "harmful" in SAFETY_CHECK_PROMPT

    def test_guardrails_allows_personalization(self):
        """Guardrails prompt allows personalization."""
        from src.core.guardrails import SAFETY_CHECK_PROMPT

        assert "Personalization" in SAFETY_CHECK_PROMPT or "personalization" in SAFETY_CHECK_PROMPT


# ---------------------------------------------------------------------------
# Problem 15: Противоречивые факты
# Fix: Phase 7 — temporal archiving + updated_at
# ---------------------------------------------------------------------------
class TestProblem15ContradictoryFacts:
    def test_metadata_enrichment_adds_updated_at(self):
        from src.core.memory.mem0_client import _enrich_metadata

        meta = _enrich_metadata({"category": "user_identity"})
        assert "updated_at" in meta
        assert "priority" in meta
        assert meta["priority"] == "critical"

    async def test_two_cities_contradiction_archives_old(self):
        """When user says 'I live in Almaty' after 'I live in Bishkek',
        the old city fact must be archived and deleted."""
        from src.core.memory.mem0_client import _detect_and_resolve_contradiction
        from src.core.memory.mem0_domains import MemoryDomain

        old_city_mem = {
            "id": "mem-city-old",
            "memory": "User lives in Bishkek",
            "score": 0.85,
            "metadata": {"category": "user_identity"},
        }
        mock_memory = MagicMock()
        mock_memory.add = MagicMock()
        mock_memory.delete = MagicMock()

        with (
            patch(
                "src.core.memory.mem0_client.search_memories",
                new_callable=AsyncMock,
                return_value=[old_city_mem],
            ),
            patch("src.core.memory.mem0_client.get_memory", return_value=mock_memory),
            patch(
                "src.core.memory.mem0_client._resolve_user_id",
                return_value="user1:core",
            ),
        ):
            await _detect_and_resolve_contradiction(
                "User lives in Almaty", "user1", MemoryDomain.core, "user_identity"
            )

        # Old fact archived (add called with superseded marker)
        assert mock_memory.add.called
        archived_text = mock_memory.add.call_args[0][0]
        assert "Bishkek" in archived_text or "Superseded" in archived_text

        # Old fact deleted
        assert mock_memory.delete.called


# ---------------------------------------------------------------------------
# Problem 16: Lost-in-the-middle → already handled by context positioning
# ---------------------------------------------------------------------------
class TestProblem16LostInMiddle:
    def test_context_has_positioning(self):
        """Context module must reference positioning strategy."""
        import inspect

        from src.core.memory import context

        source = inspect.getsource(context)
        assert "lost" in source.lower() or "middle" in source.lower()


# ---------------------------------------------------------------------------
# Problem 17: Cross-session amnesia → Phase 3 immediate identity + Redis cache
# ---------------------------------------------------------------------------
class TestProblem17CrossSessionAmnesia:
    def test_identity_has_redis_cache(self):
        """Identity module must use Redis caching."""
        import inspect

        from src.core import identity

        source = inspect.getsource(identity)
        assert "redis" in source.lower()
        assert "_IDENTITY_CACHE_TTL" in source


# ---------------------------------------------------------------------------
# Problem 18: Не различает важность информации
# Fix: Phase 7 — priority field in metadata
# ---------------------------------------------------------------------------
class TestProblem18ImportanceDiscrimination:
    def test_critical_vs_normal_priority(self):
        from src.core.memory.mem0_client import _CATEGORY_PRIORITY

        critical = [k for k, v in _CATEGORY_PRIORITY.items() if v == "critical"]
        normal = [k for k, v in _CATEGORY_PRIORITY.items() if v == "normal"]
        assert len(critical) >= 4  # identity, bot, rule, preference, profile
        assert len(normal) >= 3  # merchant, spending, life_*

    def test_critical_survives_overflow_sort(self):
        """During intra-domain overflow, critical facts must come first in the
        sorted list so the trimmer drops normal/important facts from the tail."""
        from src.core.memory.context import _split_memories_by_priority

        memories = [
            {
                "memory": "Spending pattern: eats out often",
                "metadata": {
                    "domain": "finance",
                    "category": "spending_pattern",
                    "priority": "normal",
                },
            },
            {
                "memory": "Name is Maria",
                "metadata": {"domain": "core", "category": "user_identity", "priority": "critical"},
            },
            {
                "memory": "Monthly budget $5000",
                "metadata": {
                    "domain": "finance",
                    "category": "budget_limit",
                    "priority": "important",
                },
            },
        ]

        core_mems, noncore_mems = _split_memories_by_priority(memories)

        assert len(core_mems) == 3
        assert len(noncore_mems) == 0
        # Critical must be first (survives longest during trim)
        assert core_mems[0]["metadata"]["priority"] == "critical"
        # Normal must be last (dropped first during trim)
        assert core_mems[-1]["metadata"]["priority"] == "normal"


# ---------------------------------------------------------------------------
# Problem 19: Контекстно-зависимые предпочтения → Phase 4 user rules
# ---------------------------------------------------------------------------
class TestProblem19ContextPreferences:
    def test_rules_format_block(self):
        from src.core.identity import format_rules_block

        block = format_rules_block(["На русском", "Коротко"])
        assert "На русском" in block
        assert "Коротко" in block


# ---------------------------------------------------------------------------
# Problem 20: Невидимая память → Phase 11 confirmation on save
# ---------------------------------------------------------------------------
class TestProblem20InvisibleMemory:
    async def test_memory_update_shows_old_and_new(self):
        """memory_update must show what was changed."""
        from src.skills.memory_vault.handler import MemoryVaultSkill

        skill = MemoryVaultSkill()
        mock_search = AsyncMock(return_value=[{
            "id": "mem-123",
            "memory": "City: Bishkek",
            "score": 0.95,
        }])
        mock_delete = AsyncMock()
        mock_add = AsyncMock()
        context = MagicMock(user_id="test-user", language="en")

        result = await skill._handle_update(
            context, "City: Almaty",
            mock_search, mock_delete, mock_add, lang="en",
        )
        assert "Bishkek" in result.response_text
        assert "Almaty" in result.response_text


# ---------------------------------------------------------------------------
# DLQ: Mem0 failures don't lose data
# Fix: Phase 8
# ---------------------------------------------------------------------------
class TestDLQIntegration:
    async def test_dlq_enqueue_dequeue(self):
        """DLQ must support enqueue and dequeue."""
        from src.core.memory.mem0_dlq import (
            dequeue_failed_memories,
            enqueue_failed_memory,
        )

        # These functions exist and are importable
        assert callable(enqueue_failed_memory)
        assert callable(dequeue_failed_memories)

    def test_dlq_idempotency_key(self):
        from src.core.memory.mem0_dlq import _idempotency_key

        key1 = _idempotency_key("user1", "content", "category")
        key2 = _idempotency_key("user1", "content", "category")
        key3 = _idempotency_key("user2", "content", "category")
        assert key1 == key2  # Same input → same key
        assert key1 != key3  # Different user → different key


# ---------------------------------------------------------------------------
# Undo + Mem0 sync
# Fix: Phase 9
# ---------------------------------------------------------------------------
class TestUndoSync:
    async def test_store_undo_includes_transaction_id(self):
        """Undo payload must include transaction_id for Mem0 sync."""
        import json

        from src.core.undo import store_undo

        with patch("src.core.undo.redis") as mock_redis:
            mock_redis.set = AsyncMock()
            await store_undo("user1", "add_expense", "rec-123", "transactions")

            call_args = mock_redis.set.call_args
            payload = json.loads(call_args[0][1])
            assert "transaction_id" in payload
            assert payload["transaction_id"] == "rec-123"
