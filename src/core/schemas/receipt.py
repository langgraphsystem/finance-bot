from decimal import Decimal

from pydantic import BaseModel


class ReceiptItem(BaseModel):
    name: str
    quantity: float = 1.0
    price: Decimal


class ReceiptData(BaseModel):
    merchant: str
    total: Decimal
    date: str | None = None
    items: list[ReceiptItem] = []
    tax: Decimal | None = None
    payment_method: str | None = None
    state: str | None = None
    gallons: float | None = None
    price_per_gallon: Decimal | None = None
    address: str | None = None
