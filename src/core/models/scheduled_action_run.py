import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import RunStatus


class ScheduledActionRun(Base, TimestampMixin):
    __tablename__ = "scheduled_action_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scheduled_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_actions.id", ondelete="CASCADE"),
    )
    planned_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        ENUM(RunStatus, name="run_status", create_type=False),
        default=RunStatus.pending,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    action = relationship("ScheduledAction", back_populates="runs")
