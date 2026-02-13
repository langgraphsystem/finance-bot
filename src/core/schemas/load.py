from decimal import Decimal

from pydantic import BaseModel


class LoadData(BaseModel):
    broker: str
    origin: str
    destination: str
    rate: Decimal
    ref_number: str | None = None
    pickup_date: str | None = None
    delivery_date: str | None = None
