"""Tests for domain definitions and intent-domain mapping."""

from src.core.domains import INTENT_DOMAIN_MAP, Domain


def test_domain_enum_has_all_domains():
    """All expected domains exist."""
    expected = {
        "finance",
        "finance_specialist",
        "email",
        "calendar",
        "brief",
        "tasks",
        "research",
        "writing",
        "contacts",
        "booking",
        "web",
        "monitor",
        "sheets",
        "general",
        "onboarding",
        "document",
    }
    actual = {d.value for d in Domain}
    assert expected == actual


def test_all_finance_intents_map_to_finance():
    """All finance intents should map to Domain.finance."""
    finance_intents = [
        "add_expense",
        "add_income",
        "scan_receipt",
        "query_stats",
        "query_report",
        "correct_category",
        "undo_last",
        "mark_paid",
        "set_budget",
        "add_recurring",
        "complex_query",
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


def test_booking_intents_map_correctly():
    """Booking and CRM intents should map to correct domains."""
    assert INTENT_DOMAIN_MAP["create_booking"] == Domain.booking
    assert INTENT_DOMAIN_MAP["list_bookings"] == Domain.booking
    assert INTENT_DOMAIN_MAP["cancel_booking"] == Domain.booking
    assert INTENT_DOMAIN_MAP["reschedule_booking"] == Domain.booking
    assert INTENT_DOMAIN_MAP["add_contact"] == Domain.contacts
    assert INTENT_DOMAIN_MAP["list_contacts"] == Domain.contacts
    assert INTENT_DOMAIN_MAP["find_contact"] == Domain.contacts
    assert INTENT_DOMAIN_MAP["send_to_client"] == Domain.booking


def test_document_intents_map_correctly():
    """Document agent intents should map to document domain."""
    document_intents = [
        "scan_document",
        "convert_document",
        "list_documents",
        "search_documents",
        "extract_table",
        "fill_template",
        "fill_pdf_form",
        "analyze_document",
        "merge_documents",
        "pdf_operations",
        "generate_spreadsheet",
        "compare_documents",
        "summarize_document",
        "generate_document",
        "generate_presentation",
    ]
    for intent in document_intents:
        assert INTENT_DOMAIN_MAP[intent] == Domain.document, f"{intent} not in document"


def test_finance_specialist_intents_map_correctly():
    """Wave 1 financial specialist intents should map to finance_specialist domain."""
    specialist_intents = [
        "financial_summary",
        "generate_invoice",
        "tax_estimate",
        "cash_flow_forecast",
    ]
    for intent in specialist_intents:
        assert INTENT_DOMAIN_MAP[intent] == Domain.finance_specialist, (
            f"{intent} not in finance_specialist"
        )


def test_all_current_intents_are_mapped():
    """All current intents should be in the map."""
    current_intents = {
        "add_expense",
        "add_income",
        "scan_receipt",
        "scan_document",
        "query_stats",
        "query_report",
        "correct_category",
        "undo_last",
        "mark_paid",
        "set_budget",
        "add_recurring",
        "complex_query",
        "quick_capture",
        "track_food",
        "track_drink",
        "mood_checkin",
        "day_plan",
        "day_reflection",
        "life_search",
        "set_comm_mode",
        "general_chat",
        "onboarding",
        "create_booking",
        "list_bookings",
        "cancel_booking",
        "reschedule_booking",
        "add_contact",
        "list_contacts",
        "find_contact",
        "send_to_client",
        "convert_document",
        "list_documents",
        "search_documents",
        "extract_table",
    }
    for intent in current_intents:
        assert intent in INTENT_DOMAIN_MAP, f"{intent} missing from INTENT_DOMAIN_MAP"


def test_intent_domain_map_values_are_valid_domains():
    """Every value in INTENT_DOMAIN_MAP should be a valid Domain enum member."""
    for intent, domain in INTENT_DOMAIN_MAP.items():
        assert isinstance(domain, Domain), f"{intent} maps to non-Domain: {domain}"
