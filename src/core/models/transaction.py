import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID, ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import Scope, TransactionType


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"))
    type: Mapped[TransactionType] = mapped_column(
        ENUM(TransactionType, name="transaction_type", create_type=False)
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    original_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    exchange_rate: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[date] = mapped_column(Date)
    scope: Mapped[Scope] = mapped_column(ENUM(Scope, name="scope", create_type=False))
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    ai_confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0)
    is_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    category = relationship("Category")
    user = relationship("User")
