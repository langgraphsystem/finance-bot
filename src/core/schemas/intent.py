from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class ClarifyCandidate(BaseModel):
    """One candidate intent during disambiguation."""

    intent: str
    label: str  # Russian, user-facing, e.g. "Записать расход"
    confidence: float


class IntentData(BaseModel):
    amount: Decimal | None = None
    merchant: str | None = None
    category: str | None = None
    scope: str | None = None
    date: str | None = None
    description: str | None = None
    currency: str | None = None
    period: str | None = None  # today, week, month, year, custom
    date_from: str | None = None  # YYYY-MM-DD for custom range
    date_to: str | None = None  # YYYY-MM-DD for custom range

    # Export fields
    export_type: str | None = None  # expenses, tasks, contacts

    # Life-tracking fields
    tags: list[str] | None = None
    project: str | None = None
    note: str | None = None
    reflection: str | None = None
    food_item: str | None = None
    meal_type: str | None = None
    drink_type: str | None = None
    drink_count: int | None = None
    drink_volume_ml: int | None = None
    mood: int | None = None
    energy: int | None = None
    stress: int | None = None
    sleep_hours: float | None = None
    tasks: list[str] | None = None
    comm_mode: str | None = None
    search_query: str | None = None
    life_event_type: str | None = None  # note, food, drink, mood, task, reflection

    # Domain (set by router or 2-stage detection)
    domain: str | None = None  # finance, email, calendar, tasks, etc.

    # Email fields (Phase 2)
    email_to: str | None = None
    email_subject: str | None = None
    email_body_hint: str | None = None

    # Calendar fields (Phase 2)
    event_title: str | None = None
    event_datetime: str | None = None
    event_duration_minutes: int | None = None
    event_attendees: list[str] | None = None

    # Task fields (Phase 3)
    task_title: str | None = None
    task_deadline: str | None = None
    task_priority: str | None = None
    reminder_recurrence: str | None = None  # "daily", "weekly", "monthly"
    reminder_end_date: str | None = None  # "YYYY-MM-DD"
    schedule_frequency: str | None = None  # once, daily, weekly, monthly, weekdays, cron
    schedule_time: str | None = None  # "08:00", "7:30 AM"
    schedule_day_of_week: str | None = None  # monday, пн, Mon-Fri
    schedule_day_of_month: int | None = None  # 1..31
    schedule_sources: list[str] | None = None  # ["calendar", "tasks", "money_summary"]
    schedule_instruction: str | None = None  # what to include in summary
    schedule_output_mode: str | None = None  # compact, decision_ready
    schedule_action_kind: str | None = None  # digest, outcome
    schedule_completion_condition: str | None = None  # empty, task_completed, invoice_paid
    schedule_end_date: str | None = None  # YYYY-MM-DD
    schedule_max_runs: int | None = None  # stop after N runs
    managed_action_title: str | None = None  # target action title for management ops
    manage_operation: str | None = None  # pause, resume, delete, reschedule, modify
    added_sources: list[str] | None = None  # ["email_highlights", "money_summary"]
    removed_sources: list[str] | None = None  # ["calendar"]
    new_instruction: str | None = None  # updated instruction text

    # Research fields (Phase 3)
    search_topic: str | None = None
    maps_query: str | None = None  # place/address search query
    maps_mode: str | None = None  # "search" or "directions"
    destination: str | None = None  # destination for directions
    youtube_query: str | None = None  # YouTube video search query
    detail_mode: bool | None = None  # true = use direct API for richer results

    # Writing fields (Phase 3)
    writing_topic: str | None = None
    target_language: str | None = None
    target_platform: str | None = None

    # Contact fields (Phase 3)
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None

    # Delete data fields
    # expenses, income, transactions, food, drinks, mood, notes,
    # life_events, tasks, shopping, messages, all
    delete_scope: str | None = None

    # Shopping list fields
    shopping_items: list[str] | None = None
    shopping_list_name: str | None = None
    shopping_item_remove: str | None = None

    # Booking fields (Phase 6)
    booking_title: str | None = None
    booking_service_type: str | None = None
    booking_location: str | None = None
    booking_contact_role: str | None = None

    # Visual card generation
    card_topic: str | None = None

    # Image generation
    image_prompt: str | None = None

    # Code generation
    program_description: str | None = None
    program_language: str | None = None
    # Code modification
    program_changes: str | None = None
    program_id: str | None = None

    # Geolocation: auto-detected city from message text
    detected_city: str | None = None
    # maps_search: whether user specified an explicit location (address, place, city)
    location_specified: bool | None = None

    # Document fields
    target_format: str | None = None  # "pdf", "docx", "xlsx", "epub", etc.
    document_type: str | None = None  # filter for list_documents
    template_name: str | None = None  # for fill_template
    output_format: str | None = None  # "pdf", "docx", "xlsx"
    analysis_question: str | None = None  # for analyze_document
    document_description: str | None = None  # for generate_document
    pdf_operation: str | None = None  # split, rotate, encrypt, decrypt, watermark, extract_pages
    pdf_pages: str | None = None  # "3-7", "1,3,5", "all"
    pdf_password: str | None = None  # for encrypt/decrypt
    presentation_topic: str | None = None  # for generate_presentation

    # Google Sheets fields
    sheet_url: str | None = None  # spreadsheet URL or ID
    sheet_range: str | None = None  # cell range like "A1:D10" or "Sheet1"
    sheet_data: str | None = None  # data to write/append (free text, LLM parses)

    # Browser action fields
    browser_target_site: str | None = None  # "booking.com", "amazon.com"
    browser_task: str | None = None  # "book hotel in Barcelona for March 15-18"

    # Hotel booking fields (extracted by intent detection for browser_action)
    hotel_city: str | None = None
    hotel_check_in: str | None = None  # YYYY-MM-DD
    hotel_check_out: str | None = None  # YYYY-MM-DD
    hotel_guests: int | None = None
    hotel_budget: float | None = None
    hotel_platform: str | None = None  # "booking.com", "airbnb.com"

    # Receptionist fields
    receptionist_topic: str | None = None  # "services", "hours", "faq", "general"

    # Invoice fields
    invoice_items: list[dict] | None = None  # [{description, amount, quantity?}]
    invoice_due_days: int | None = None  # "net 15" → 15
    invoice_notes: str | None = None  # custom notes
    requires_sales_tax: bool | None = None
    invoice_tax_category: str | None = None
    invoice_tax_category_code: str | None = None
    seller_state: str | None = None
    buyer_address_line1: str | None = None
    buyer_city: str | None = None
    buyer_state: str | None = None
    buyer_postal_code: str | None = None
    buyer_country: str | None = None

    # Memory Vault fields
    memory_query: str | None = None  # search/delete/save content for memory_vault

    # User Rules / Personalization fields
    rule_text: str | None = None  # user rule content for set_user_rule

    # Project Context fields (Phase 12)
    project_name: str | None = None  # for set_project, create_project


class IntentDetectionResult(BaseModel):
    intent: str
    confidence: float
    intent_type: Literal["chat", "action", "clarify"] = "action"
    data: IntentData | None = None
    response: str | None = None
    clarify_candidates: list[ClarifyCandidate] | None = None
