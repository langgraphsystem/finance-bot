"""Tests for Mem0 domain segmentation (Phase 2.1)."""

from src.core.memory.mem0_domains import (
    CATEGORY_DOMAIN_MAP,
    INTENT_DOMAIN_MEM_MAP,
    MEM_TYPE_DOMAIN_MAP,
    TEMPORAL_HISTORY_INTENTS,
    TEMPORAL_SIMILARITY_THRESHOLD,
    UPDATABLE_CATEGORIES,
    MemoryDomain,
    get_domain_for_category,
    get_domains_for_intent,
    scoped_user_id,
)


class TestMemoryDomain:
    def test_has_12_domains(self):
        assert len(MemoryDomain) == 12

    def test_domain_values(self):
        assert MemoryDomain.core.value == "core"
        assert MemoryDomain.finance.value == "finance"
        assert MemoryDomain.life.value == "life"
        assert MemoryDomain.procedures.value == "procedures"


class TestScopedUserId:
    def test_basic_scoping(self):
        assert scoped_user_id("u123", MemoryDomain.finance) == "u123:finance"

    def test_different_domains(self):
        assert scoped_user_id("u1", MemoryDomain.core) == "u1:core"
        assert scoped_user_id("u1", MemoryDomain.life) == "u1:life"

    def test_uuid_format(self):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        result = scoped_user_id(uid, MemoryDomain.finance)
        assert result == f"{uid}:finance"


class TestGetDomainForCategory:
    def test_finance_categories(self):
        assert get_domain_for_category("income") == MemoryDomain.finance
        assert get_domain_for_category("budget_limit") == MemoryDomain.finance
        assert get_domain_for_category("merchant_mapping") == MemoryDomain.finance

    def test_life_categories(self):
        assert get_domain_for_category("life_note") == MemoryDomain.life
        assert get_domain_for_category("life_pattern") == MemoryDomain.life

    def test_core_categories(self):
        assert get_domain_for_category("profile") == MemoryDomain.core

    def test_unknown_defaults_to_core(self):
        assert get_domain_for_category("unknown_cat") == MemoryDomain.core

    def test_fact_history_mapped(self):
        assert get_domain_for_category("fact_history") == MemoryDomain.finance


class TestGetDomainsForIntent:
    def test_add_expense_returns_finance(self):
        domains = get_domains_for_intent("add_expense", "mappings")
        assert domains == [MemoryDomain.finance]

    def test_complex_query_returns_multiple(self):
        domains = get_domains_for_intent("complex_query", "all")
        assert MemoryDomain.finance in domains
        assert MemoryDomain.core in domains
        assert MemoryDomain.life in domains

    def test_morning_brief_returns_all(self):
        domains = get_domains_for_intent("morning_brief", "life")
        assert len(domains) == 12

    def test_unmapped_intent_uses_mem_type(self):
        # some_future_intent not in INTENT_DOMAIN_MEM_MAP → falls back to mem_type
        domains = get_domains_for_intent("some_future_intent", "profile")
        assert domains == MEM_TYPE_DOMAIN_MAP["profile"]

    def test_unmapped_intent_and_mem_type_fallback(self):
        domains = get_domains_for_intent("some_new_intent", True)
        assert MemoryDomain.core in domains
        assert MemoryDomain.finance in domains

    def test_false_mem_type_returns_empty(self):
        domains = get_domains_for_intent("some_intent", False)
        assert domains == []


class TestCategoryDomainMap:
    def test_all_extraction_categories_mapped(self):
        expected = {
            "profile", "income", "recurring_expense", "budget_limit",
            "merchant_mapping", "correction_rule", "spending_pattern",
            "life_note", "life_pattern", "life_preference",
            "contact", "document_preference", "writing_style",
            "task_habit", "calendar_preference", "research_interest",
            "episode", "procedure", "fact_history",
        }
        assert expected.issubset(set(CATEGORY_DOMAIN_MAP.keys()))


class TestMemTypeDomainMap:
    def test_all_covers_all_domains(self):
        assert set(MEM_TYPE_DOMAIN_MAP["all"]) == set(MemoryDomain)

    def test_mappings_is_finance(self):
        assert MEM_TYPE_DOMAIN_MAP["mappings"] == [MemoryDomain.finance]

    def test_life_includes_core(self):
        assert MemoryDomain.core in MEM_TYPE_DOMAIN_MAP["life"]


class TestTemporalConstants:
    def test_updatable_categories_are_fact_types(self):
        assert "income" in UPDATABLE_CATEGORIES
        assert "budget_limit" in UPDATABLE_CATEGORIES
        assert "profile" in UPDATABLE_CATEGORIES
        # Additive categories should NOT be updatable
        assert "episode" not in UPDATABLE_CATEGORIES
        assert "life_note" not in UPDATABLE_CATEGORIES

    def test_similarity_threshold(self):
        assert 0.0 < TEMPORAL_SIMILARITY_THRESHOLD < 1.0

    def test_temporal_history_intents(self):
        assert "complex_query" in TEMPORAL_HISTORY_INTENTS
        assert "financial_summary" in TEMPORAL_HISTORY_INTENTS
        # Simple intents should not load history
        assert "add_expense" not in TEMPORAL_HISTORY_INTENTS


class TestIntentDomainMemMap:
    def test_all_mapped_intents_have_lists(self):
        for intent, domains in INTENT_DOMAIN_MEM_MAP.items():
            assert isinstance(domains, list), f"{intent} should map to a list"
            assert len(domains) > 0, f"{intent} should have at least one domain"

    def test_finance_intents_include_finance(self):
        for intent in ["add_expense", "add_income", "scan_receipt"]:
            assert MemoryDomain.finance in INTENT_DOMAIN_MEM_MAP[intent]
