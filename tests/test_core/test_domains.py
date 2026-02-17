"""Tests for domain definitions and intent-domain mapping."""

from src.core.domains import INTENT_DOMAIN_MAP, Domain


def test_domain_enum_has_all_domains():
    """All expected domains exist."""
    expected = {
        "finance", "email", "calendar", "tasks", "research",
        "writing", "contacts", "web", "monitor", "general", "onboarding",
    }
    actual = {d.value for d in Domain}
    assert expected == actual


def test_all_finance_intents_map_to_finance():
    """All finance intents should map to Domain.finance."""
    finance_intents = [
        "add_expense", "add_income", "scan_receipt", "scan_document",
        "query_stats", "query_report", "correct_category", "undo_last",
        "mark_paid", "set_budget", "add_recurring", "complex_query",
    ]
    for intent in finance_intents:
        assert INTENT_DOMAIN_MAP[intent] == Domain.finance, f"{intent} not in finance"


def test_life_intents_map_correctly():
    """Life-tracking intents should map to correct domains."""
    assert INTENT_DOMAIN_MAP["quick_capture"] == Domain.general
    assert INTENT_DOMAIN_MAP["track_food"] == Domain.general
    assert INTENT_DOMAIN_MAP["track_drink"] == Domain.general
    assert INTENT_DOMAIN_MAP["mood_checkin"] == Domain.general
    assert INTENT_DOMAIN_MAP["day_plan"] == Domain.tasks
    assert INTENT_DOMAIN_MAP["day_reflection"] == Domain.general
    assert INTENT_DOMAIN_MAP["life_search"] == Domain.general
    assert INTENT_DOMAIN_MAP["set_comm_mode"] == Domain.general


def test_general_chat_maps_to_general():
    assert INTENT_DOMAIN_MAP["general_chat"] == Domain.general


def test_onboarding_maps_to_onboarding():
    assert INTENT_DOMAIN_MAP["onboarding"] == Domain.onboarding


def test_all_current_intents_are_mapped():
    """All 22 current intents should be in the map."""
    current_intents = {
        "add_expense", "add_income", "scan_receipt", "scan_document",
        "query_stats", "query_report", "correct_category", "undo_last",
        "mark_paid", "set_budget", "add_recurring", "complex_query",
        "quick_capture", "track_food", "track_drink", "mood_checkin",
        "day_plan", "day_reflection", "life_search", "set_comm_mode",
        "general_chat", "onboarding",
    }
    for intent in current_intents:
        assert intent in INTENT_DOMAIN_MAP, f"{intent} missing from INTENT_DOMAIN_MAP"


def test_intent_domain_map_values_are_valid_domains():
    """Every value in INTENT_DOMAIN_MAP should be a valid Domain enum member."""
    for intent, domain in INTENT_DOMAIN_MAP.items():
        assert isinstance(domain, Domain), f"{intent} maps to non-Domain: {domain}"
