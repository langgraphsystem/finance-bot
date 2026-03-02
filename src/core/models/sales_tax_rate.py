import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, TimestampMixin


class SalesTaxRateCache(Base, TimestampMixin):
    """Cache of resolved US sales-tax rates for invoice generation."""

    __tablename__ = "sales_tax_rate_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_state: Mapped[str] = mapped_column(String(16))
    buyer_state: Mapped[str] = mapped_column(String(16))
    buyer_postal_code: Mapped[str] = mapped_column(String(20))
    tax_category: Mapped[str] = mapped_column(String(64), default="general")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    tax_rate: Mapped[float] = mapped_column(Numeric(8, 6), default=0)
    source: Mapped[str] = mapped_column(String(32), default="stripe")
    jurisdiction: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
