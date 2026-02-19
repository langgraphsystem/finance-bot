"""Domain definitions for multi-domain routing.

Each intent maps to a domain. The DomainRouter uses this mapping
to delegate intents to either a LangGraph orchestrator (complex domains)
or the existing AgentRouter (simple CRUD domains).
"""

from enum import StrEnum


class Domain(StrEnum):
    finance = "finance"
    email = "email"
    calendar = "calendar"
    tasks = "tasks"
    research = "research"
    writing = "writing"
    contacts = "contacts"
    web = "web"
    monitor = "monitor"
    general = "general"
    onboarding = "onboarding"


# Maps each intent to its domain.
# Finance and life-tracking intents are pre-populated.
# New domains add their intents here as they are implemented.
INTENT_DOMAIN_MAP: dict[str, Domain] = {
    # Finance (existing 14 intents)
    "add_expense": Domain.finance,
    "add_income": Domain.finance,
    "scan_receipt": Domain.finance,
    "scan_document": Domain.finance,
    "query_stats": Domain.finance,
    "query_report": Domain.finance,
    "correct_category": Domain.finance,
    "undo_last": Domain.finance,
    "mark_paid": Domain.finance,
    "set_budget": Domain.finance,
    "add_recurring": Domain.finance,
    "complex_query": Domain.finance,
    # Life-tracking (existing 8 intents)
    "quick_capture": Domain.general,
    "track_food": Domain.general,
    "track_drink": Domain.general,
    "mood_checkin": Domain.general,
    "day_plan": Domain.tasks,
    "day_reflection": Domain.general,
    "life_search": Domain.general,
    "set_comm_mode": Domain.general,
    # Tasks & Reminders (4 new intents)
    "create_task": Domain.tasks,
    "list_tasks": Domain.tasks,
    "set_reminder": Domain.tasks,
    "complete_task": Domain.tasks,
    # Research & Answers (3 new intents)
    "quick_answer": Domain.research,
    "web_search": Domain.research,
    "compare_options": Domain.research,
    # Writing Assistance (4 intents)
    "draft_message": Domain.writing,
    "translate_text": Domain.writing,
    "write_post": Domain.writing,
    "proofread": Domain.writing,
    # Email (5 intents)
    "read_inbox": Domain.email,
    "send_email": Domain.email,
    "draft_reply": Domain.email,
    "follow_up_email": Domain.email,
    "summarize_thread": Domain.email,
    # Calendar (5 intents)
    "list_events": Domain.calendar,
    "create_event": Domain.calendar,
    "find_free_slots": Domain.calendar,
    "reschedule_event": Domain.calendar,
    "morning_brief": Domain.calendar,
    # General
    "general_chat": Domain.general,
    "onboarding": Domain.onboarding,
    "evening_recap": Domain.general,
}
