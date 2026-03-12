"""Mem0 domain segmentation — hard namespace isolation via scoped user_id.

Each domain gets its own vector space: `{user_id}:{domain}`.
This prevents cross-contamination (finance facts polluting life context)
and enables targeted loading per intent.
"""

from enum import StrEnum


class MemoryDomain(StrEnum):
    """12 memory domains for namespace isolation."""

    core = "core"  # name, language, timezone, comm preferences
    finance = "finance"  # expenses, income, budgets, merchant mappings
    life = "life"  # food, drink, mood, energy, sleep, notes
    contacts = "contacts"  # people, relationships, companies
    documents = "documents"  # document preferences, templates
    content = "content"  # writing style, tone, post preferences
    tasks = "tasks"  # habits, routines, reminders
    calendar = "calendar"  # scheduling preferences, recurring events
    research = "research"  # interests, topics, saved searches
    episodes = "episodes"  # past interactions, outcomes
    procedures = "procedures"  # learned rules, corrections, workflows
    projects = "projects"  # user projects, goals, status


# Map metadata category (from FINANCIAL_FACT_EXTRACTION_PROMPT) to domain
CATEGORY_DOMAIN_MAP: dict[str, MemoryDomain] = {
    "profile": MemoryDomain.core,
    "income": MemoryDomain.finance,
    "recurring_expense": MemoryDomain.finance,
    "budget_limit": MemoryDomain.finance,
    "merchant_mapping": MemoryDomain.finance,
    "correction_rule": MemoryDomain.finance,
    "spending_pattern": MemoryDomain.finance,
    "life_note": MemoryDomain.life,
    "life_pattern": MemoryDomain.life,
    "life_preference": MemoryDomain.life,
    "life_digest": MemoryDomain.life,
    "life_insights": MemoryDomain.life,
    "contact": MemoryDomain.contacts,
    "document_preference": MemoryDomain.documents,
    "writing_style": MemoryDomain.content,
    "content": MemoryDomain.content,
    "task_habit": MemoryDomain.tasks,
    "calendar_preference": MemoryDomain.calendar,
    "research_interest": MemoryDomain.research,
    "episode": MemoryDomain.episodes,
    "procedure": MemoryDomain.procedures,
    # Temporal fact tracking — archived superseded facts
    "fact_history": MemoryDomain.finance,
    # Observational memory — behavioral patterns extracted by Observer
    "observation": MemoryDomain.episodes,
    # Project context (Phase 12)
    "user_project": MemoryDomain.projects,
    "project_goal": MemoryDomain.projects,
    "project_status": MemoryDomain.projects,
    "project_fact": MemoryDomain.projects,
    # Program / code-generation memory
    "program_artifact": MemoryDomain.core,
}

# Map QUERY_CONTEXT_MAP "mem" values to which domains to search
MEM_TYPE_DOMAIN_MAP: dict[str, list[MemoryDomain]] = {
    "all": list(MemoryDomain),
    "mappings": [MemoryDomain.finance],
    "profile": [MemoryDomain.core, MemoryDomain.finance],
    "budgets": [MemoryDomain.finance],
    "life": [MemoryDomain.life, MemoryDomain.core],
}

# Map intents to which domains to search (overrides mem_type when set)
INTENT_DOMAIN_MEM_MAP: dict[str, list[MemoryDomain]] = {
    # Finance: only finance domain
    "add_expense": [MemoryDomain.finance],
    "add_income": [MemoryDomain.finance],
    "scan_receipt": [MemoryDomain.finance],
    "correct_category": [MemoryDomain.finance],
    "set_budget": [MemoryDomain.finance],
    # Analytics: finance + core (fact_history loaded separately for temporal queries)
    "query_stats": [MemoryDomain.finance, MemoryDomain.core],
    "complex_query": [MemoryDomain.finance, MemoryDomain.core, MemoryDomain.life],
    "financial_summary": [MemoryDomain.finance, MemoryDomain.core],
    "tax_estimate": [MemoryDomain.finance],
    "cash_flow_forecast": [MemoryDomain.finance],
    # Life: life + core
    "track_food": [MemoryDomain.life],
    "track_drink": [MemoryDomain.life],
    "mood_checkin": [MemoryDomain.life],
    "day_plan": [MemoryDomain.life, MemoryDomain.tasks],
    "day_reflection": [MemoryDomain.life],
    "life_search": [MemoryDomain.life, MemoryDomain.core],
    # Brief: load everything
    "morning_brief": list(MemoryDomain),
    "evening_recap": list(MemoryDomain),
    # Email/Writing: core + content
    "send_email": [MemoryDomain.core, MemoryDomain.content, MemoryDomain.contacts],
    "draft_reply": [MemoryDomain.core, MemoryDomain.content],
    "draft_message": [MemoryDomain.core, MemoryDomain.content],
    "write_post": [MemoryDomain.content, MemoryDomain.core],
    # Booking/CRM: contacts + core
    "create_booking": [MemoryDomain.contacts, MemoryDomain.core],
    "receptionist": [MemoryDomain.contacts, MemoryDomain.core],
    "send_to_client": [MemoryDomain.contacts, MemoryDomain.core],
    # Finance: remaining intents
    "mark_paid": [MemoryDomain.finance],
    "add_recurring": [MemoryDomain.finance],
    "undo_last": [MemoryDomain.finance],
    "delete_data": [MemoryDomain.finance],
    "export_excel": [MemoryDomain.finance],
    "query_report": [MemoryDomain.finance, MemoryDomain.core],
    "generate_invoice": [MemoryDomain.finance, MemoryDomain.contacts],
    # Tasks
    "create_task": [MemoryDomain.tasks],
    "list_tasks": [MemoryDomain.tasks],
    "complete_task": [MemoryDomain.tasks],
    "shopping_list_add": [MemoryDomain.tasks],
    "shopping_list_view": [MemoryDomain.tasks],
    "shopping_list_remove": [MemoryDomain.tasks],
    "shopping_list_clear": [MemoryDomain.tasks],
    "schedule_action": [MemoryDomain.tasks],
    "list_scheduled_actions": [MemoryDomain.tasks],
    "manage_scheduled_action": [MemoryDomain.tasks],
    # Calendar
    "list_events": [MemoryDomain.calendar, MemoryDomain.core],
    "create_event": [MemoryDomain.calendar, MemoryDomain.core],
    "find_free_slots": [MemoryDomain.calendar],
    "reschedule_event": [MemoryDomain.calendar],
    # Email: remaining
    "read_inbox": [MemoryDomain.core, MemoryDomain.contacts],
    "follow_up_email": [MemoryDomain.core, MemoryDomain.content, MemoryDomain.contacts],
    "summarize_thread": [MemoryDomain.core, MemoryDomain.contacts],
    # Research
    "quick_answer": [MemoryDomain.research],
    "web_search": [MemoryDomain.research],
    "compare_options": [MemoryDomain.research],
    "maps_search": [MemoryDomain.research],
    "youtube_search": [MemoryDomain.research],
    "price_check": [MemoryDomain.research],
    # Writing: remaining
    "translate_text": [MemoryDomain.content, MemoryDomain.core],
    "proofread": [MemoryDomain.content],
    "generate_image": [MemoryDomain.content],
    "generate_card": [MemoryDomain.content],
    "generate_program": [MemoryDomain.core],
    "modify_program": [MemoryDomain.core],
    # Document
    "generate_document": [MemoryDomain.documents, MemoryDomain.core],
    "generate_presentation": [MemoryDomain.documents, MemoryDomain.content],
    "generate_spreadsheet": [MemoryDomain.documents, MemoryDomain.finance],
    "analyze_document": [MemoryDomain.documents],
    "search_documents": [MemoryDomain.documents],
    # Booking: remaining
    "list_bookings": [MemoryDomain.contacts, MemoryDomain.core],
    "cancel_booking": [MemoryDomain.contacts],
    "reschedule_booking": [MemoryDomain.contacts],
    "list_contacts": [MemoryDomain.contacts],
    "find_contact": [MemoryDomain.contacts],
    # Life: remaining
    "quick_capture": [MemoryDomain.life],
    "set_comm_mode": [MemoryDomain.core],
    "price_alert": [MemoryDomain.life, MemoryDomain.research],
    "news_monitor": [MemoryDomain.life, MemoryDomain.research],
    "set_user_rule": [MemoryDomain.core],
    "dialog_history": [MemoryDomain.core],
    # Memory vault
    "memory_show": [MemoryDomain.life, MemoryDomain.core, MemoryDomain.finance],
    "memory_forget": [MemoryDomain.life, MemoryDomain.core, MemoryDomain.finance],
    "memory_save": [MemoryDomain.life],
    "memory_update": [MemoryDomain.core, MemoryDomain.life, MemoryDomain.finance],
    # Projects (Phase 12)
    "set_project": [MemoryDomain.projects, MemoryDomain.core],
    "create_project": [MemoryDomain.projects],
    "list_projects": [MemoryDomain.projects],
}


def get_domains_for_intent(intent: str, mem_type: str | bool) -> list[MemoryDomain]:
    """Resolve which memory domains to search for a given intent."""
    if intent in INTENT_DOMAIN_MEM_MAP:
        return INTENT_DOMAIN_MEM_MAP[intent]
    if isinstance(mem_type, str) and mem_type in MEM_TYPE_DOMAIN_MAP:
        return MEM_TYPE_DOMAIN_MAP[mem_type]
    if mem_type:
        return [MemoryDomain.core, MemoryDomain.finance]
    return []


def get_domain_for_category(category: str) -> MemoryDomain:
    """Map a metadata category to its memory domain."""
    return CATEGORY_DOMAIN_MAP.get(category, MemoryDomain.core)


def scoped_user_id(user_id: str, domain: MemoryDomain) -> str:
    """Build a domain-scoped user_id for Mem0 namespace isolation."""
    return f"{user_id}:{domain.value}"


# Categories that represent updatable facts (eligible for temporal archiving).
# When a new similar fact arrives, the old value is archived with fact_history.
UPDATABLE_CATEGORIES: frozenset[str] = frozenset({
    "profile",
    "income",
    "recurring_expense",
    "budget_limit",
    "merchant_mapping",
    "spending_pattern",
    "life_preference",
})

# Similarity threshold for considering two facts as duplicates
TEMPORAL_SIMILARITY_THRESHOLD = 0.85

# Intents that can load fact history for "how has X changed" queries
TEMPORAL_HISTORY_INTENTS: frozenset[str] = frozenset({
    "complex_query",
    "financial_summary",
    "cash_flow_forecast",
    "query_report",
})
