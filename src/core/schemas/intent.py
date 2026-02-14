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


class IntentDetectionResult(BaseModel):
    intent: str
    confidence: float
    data: IntentData | None = None
    response: str | None = None
