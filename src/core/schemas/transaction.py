import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from src.core.models.enums import Scope, TransactionType


class TransactionCreate(BaseModel):
    category_id: uuid.UUID
    type: TransactionType
    amount: Decimal = Field(gt=0)
    original_amount: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    merchant: str | None = None
    description: str | None = None
    date: date
    scope: Scope
    state: str | None = None
    meta: dict | None = None
    document_id: uuid.UUID | None = None
    ai_confidence: float = 1.0
