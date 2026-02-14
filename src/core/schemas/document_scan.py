"""Schemas for universal document scanning."""

from decimal import Decimal

from pydantic import BaseModel


class InvoiceData(BaseModel):
    vendor: str
    invoice_number: str | None = None
    date: str | None = None
    due_date: str | None = None
    total: Decimal
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    currency: str | None = None
    items: list[dict] = []
    notes: str | None = None


class GenericDocumentData(BaseModel):
    title: str | None = None
    doc_type: str | None = None
    extracted_text: str = ""
    key_values: dict = {}
    dates: list[str] = []
    amounts: list[str] = []
    summary: str = ""
