"""OrchestratorDLQ — dead-letter queue for failed graph executions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class OrchestratorDLQ(Base):
    __tablename__ = "orchestrator_dlq"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    graph_name: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(256), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id"), nullable=False
    )
    error: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retried: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    retried_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
