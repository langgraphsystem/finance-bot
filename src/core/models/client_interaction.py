"""Client interaction model — logs calls, messages, and other touchpoints."""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import InteractionChannel, InteractionDirection


class ClientInteraction(Base, TimestampMixin):
    __tablename__ = "client_interactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id")
    )
    channel: Mapped[InteractionChannel] = mapped_column(
        ENUM(InteractionChannel, name="interaction_channel", create_type=False),
    )
    direction: Mapped[InteractionDirection] = mapped_column(
        ENUM(InteractionDirection, name="interaction_direction", create_type=False),
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=True
    )
    call_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_recording_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    contact = relationship("Contact")
    booking = relationship("Booking")
