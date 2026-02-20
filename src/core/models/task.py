import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import ReminderRecurrence, TaskPriority, TaskStatus


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        ENUM(TaskStatus, name="task_status", create_type=False),
        default=TaskStatus.pending,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        ENUM(TaskPriority, name="task_priority", create_type=False),
        default=TaskPriority.medium,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    domain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Recurrence support
    recurrence: Mapped[ReminderRecurrence] = mapped_column(
        ENUM(ReminderRecurrence, name="reminder_recurrence", create_type=False),
        default=ReminderRecurrence.none,
        server_default="none",
    )
    recurrence_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    original_reminder_time: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # "HH:MM" for DST-safe recurring advancement

    user = relationship("User")
    assignee = relationship("Contact", foreign_keys=[assigned_to])
