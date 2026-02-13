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


class IntentDetectionResult(BaseModel):
    intent: str
    confidence: float
    data: IntentData | None = None
    response: str | None = None
