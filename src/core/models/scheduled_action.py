import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import ActionStatus, OutputMode, ScheduleKind


class ScheduledAction(Base, TimestampMixin):
    __tablename__ = "scheduled_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    instruction: Mapped[str] = mapped_column(Text)
    action_kind: Mapped[str] = mapped_column(String(32), default="digest")
    schedule_kind: Mapped[ScheduleKind] = mapped_column(
        ENUM(ScheduleKind, name="schedule_kind", create_type=False),
        default=ScheduleKind.daily,
    )
    schedule_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    output_mode: Mapped[OutputMode] = mapped_column(
        ENUM(OutputMode, name="output_mode", create_type=False),
        default=OutputMode.compact,
    )
    timezone: Mapped[str] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[ActionStatus] = mapped_column(
        ENUM(ActionStatus, name="action_status", create_type=False),
        default=ActionStatus.active,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    max_failures: Mapped[int] = mapped_column(Integer, default=3)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    user = relationship("User")
    runs = relationship("ScheduledActionRun", back_populates="action", cascade="all, delete-orphan")
