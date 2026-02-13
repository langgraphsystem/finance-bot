import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base
from src.core.models.enums import Scope


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    name: Mapped[str] = mapped_column(String(100))
    scope: Mapped[Scope] = mapped_column(ENUM(Scope, name="scope", create_type=False))
    icon: Mapped[str] = mapped_column(String(10), default="📦")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    business_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    family = relationship("Family", back_populates="categories")
