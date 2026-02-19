import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin


class ShoppingList(Base, TimestampMixin):
    __tablename__ = "shopping_lists"
    __table_args__ = (UniqueConstraint("family_id", "name", name="uq_shopping_list_family_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100), default="grocery")

    items = relationship("ShoppingListItem", back_populates="shopping_list", cascade="all, delete")


class ShoppingListItem(Base, TimestampMixin):
    __tablename__ = "shopping_list_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shopping_lists.id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    name: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shopping_list = relationship("ShoppingList", back_populates="items")
