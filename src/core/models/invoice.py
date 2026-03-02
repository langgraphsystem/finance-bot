import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import InvoiceStatus


class Invoice(Base, TimestampMixin):
    """Invoice record with line items stored as JSONB.

    Items format: [{"description": str, "quantity": int, "unit_price": float,
                     "amount": float, "transaction_id": str | None}]
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )

    invoice_number: Mapped[str] = mapped_column(String(20))
    status: Mapped[InvoiceStatus] = mapped_column(
        ENUM(InvoiceStatus, name="invoice_status", create_type=False),
        default=InvoiceStatus.draft,
    )

    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    subtotal: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(8, 6), default=0)
    tax_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_jurisdiction: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total: Mapped[float] = mapped_column(Numeric(12, 2))

    items: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Company info snapshots (stable even if profile changes later)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Client info snapshots
    client_name: Mapped[str] = mapped_column(String(255))
    client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Link to generated PDF document
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )

    contact = relationship("Contact")
    user = relationship("User")
