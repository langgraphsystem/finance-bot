from decimal import Decimal

from pydantic import BaseModel


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


class IntentDetectionResult(BaseModel):
    intent: str
    confidence: float
    data: IntentData | None = None
    response: str | None = None
