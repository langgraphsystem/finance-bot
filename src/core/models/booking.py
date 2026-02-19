"""Booking model for appointment scheduling."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import BookingStatus


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255))
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[BookingStatus] = mapped_column(
        ENUM(BookingStatus, name="booking_status", create_type=False),
        default=BookingStatus.scheduled,
    )
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    source_channel: Mapped[str] = mapped_column(String(50), default="telegram")
    external_calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    user = relationship("User")
    contact = relationship("Contact")
