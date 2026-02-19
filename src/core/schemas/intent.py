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

    # Shopping list fields
    shopping_items: list[str] | None = None
    shopping_list_name: str | None = None
    shopping_item_remove: str | None = None

    # Booking fields (Phase 6)
    booking_title: str | None = None
    booking_service_type: str | None = None
    booking_location: str | None = None
    booking_contact_role: str | None = None


class IntentDetectionResult(BaseModel):
    intent: str
    confidence: float
    intent_type: Literal["chat", "action", "clarify"] = "action"
    data: IntentData | None = None
    response: str | None = None
    clarify_candidates: list[ClarifyCandidate] | None = None
