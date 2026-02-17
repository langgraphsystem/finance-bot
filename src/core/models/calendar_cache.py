import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin


class CalendarCache(Base, TimestampMixin):
    __tablename__ = "calendar_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    google_event_id: Mapped[str] = mapped_column(String(255), unique=True)
    calendar_id: Mapped[str] = mapped_column(String(255), default="primary")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attendees: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User")
