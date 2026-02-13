import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base
from src.core.models.enums import Scope


class MerchantMapping(Base):
    __tablename__ = "merchant_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    merchant_pattern: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"))
    scope: Mapped[Scope] = mapped_column(ENUM(Scope, name="scope", create_type=False))
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=0.5)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    category = relationship("Category")
