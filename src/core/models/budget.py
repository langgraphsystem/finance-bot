import uuid

from sqlalchemy import Boolean, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import BudgetPeriod, Scope


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    scope: Mapped[Scope] = mapped_column(ENUM(Scope, name="scope", create_type=False))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    period: Mapped[BudgetPeriod] = mapped_column(
        ENUM(BudgetPeriod, name="budget_period", create_type=False)
    )
    alert_at: Mapped[float] = mapped_column(Numeric(3, 2), default=0.8)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category = relationship("Category")
