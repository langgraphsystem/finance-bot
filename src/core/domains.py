"""Domain definitions for multi-domain routing.

Each intent maps to a domain. The DomainRouter uses this mapping
to delegate intents to either a LangGraph orchestrator (complex domains)
or the existing AgentRouter (simple CRUD domains).
"""

from enum import StrEnum


class Domain(StrEnum):
    finance = "finance"
    finance_specialist = "finance_specialist"
    document = "document"
    email = "email"
    calendar = "calendar"
    brief = "brief"
    tasks = "tasks"
    research = "research"
    writing = "writing"
    contacts = "contacts"
    booking = "booking"
    web = "web"
    monitor = "monitor"
    sheets = "sheets"
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
    "scan_document": Domain.document,
    "query_stats": Domain.finance,
    "query_report": Domain.finance,
    "correct_category": Domain.finance,
    "undo_last": Domain.finance,
    "mark_paid": Domain.finance,
    "set_budget": Domain.finance,
    "add_recurring": Domain.finance,
    "complex_query": Domain.finance,
    "export_excel": Domain.finance,
    # Life-tracking (existing 8 intents)
    "quick_capture": Domain.general,
    "track_food": Domain.general,
    "track_drink": Domain.general,
    "mood_checkin": Domain.general,
    "create_tracker": Domain.general,
    "list_trackers": Domain.general,
    "log_tracker": Domain.general,
    "set_tracker_reminder": Domain.general,
    "day_plan": Domain.tasks,
    "day_reflection": Domain.general,
    "life_search": Domain.general,
    "set_comm_mode": Domain.general,
    # Tasks & Reminders (4 new intents)
    "create_task": Domain.tasks,
    "list_tasks": Domain.tasks,
    "set_reminder": Domain.tasks,
    "schedule_action": Domain.tasks,
    "list_scheduled_actions": Domain.tasks,
    "manage_scheduled_action": Domain.tasks,
    "complete_task": Domain.tasks,
    # Team management
    "invite_member": Domain.tasks,
    "list_members": Domain.tasks,
    "manage_member": Domain.tasks,
    # Research & Answers (3 new intents)
    "quick_answer": Domain.research,
    "web_search": Domain.research,
    "compare_options": Domain.research,
    # Document (16 intents)
    "convert_document": Domain.document,
    "list_documents": Domain.document,
    "search_documents": Domain.document,
    "extract_table": Domain.document,
    "fill_template": Domain.document,
    "fill_pdf_form": Domain.document,
    "analyze_document": Domain.document,
    "merge_documents": Domain.document,
    "pdf_operations": Domain.document,
    "generate_spreadsheet": Domain.document,
    "compare_documents": Domain.document,
    "summarize_document": Domain.document,
    "generate_document": Domain.document,
    "generate_presentation": Domain.document,
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
    "delete_event": Domain.calendar,
    "morning_brief": Domain.brief,
    # Browser + monitor (Phase 5)
    "browser_action": Domain.web,
    "web_action": Domain.web,
    "price_check": Domain.web,
    "price_alert": Domain.monitor,
    "news_monitor": Domain.monitor,
    "custom_event": Domain.monitor,
    # Booking + CRM (Phase 6)
    "create_booking": Domain.booking,
    "list_bookings": Domain.booking,
    "cancel_booking": Domain.booking,
    "reschedule_booking": Domain.booking,
    "add_contact": Domain.contacts,
    "list_contacts": Domain.contacts,
    "find_contact": Domain.contacts,
    "send_to_client": Domain.booking,
    "receptionist": Domain.booking,
    # Memory Vault
    "memory_show": Domain.general,
    "memory_forget": Domain.general,
    "memory_save": Domain.general,
    "set_user_rule": Domain.general,
    "dialog_history": Domain.general,
    "memory_update": Domain.general,
    "set_project": Domain.general,
    "create_project": Domain.general,
    "list_projects": Domain.general,
    # Google Sheets
    "read_sheets": Domain.sheets,
    "write_sheets": Domain.sheets,
    "append_sheets": Domain.sheets,
    "create_sheets": Domain.sheets,
    # General
    "general_chat": Domain.general,
    "onboarding": Domain.onboarding,
    "evening_recap": Domain.brief,
    # Wave 1 Financial Specialists
    "financial_summary": Domain.finance_specialist,
    "generate_invoice": Domain.finance_specialist,
    "tax_estimate": Domain.finance_specialist,
    "cash_flow_forecast": Domain.finance_specialist,
    # Deep Agents (intent-level orchestrators)
    "tax_report": Domain.finance_specialist,
}
