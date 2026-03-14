"""Tracker and TrackerEntry models — universal user-defined progress trackers."""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin


class Tracker(Base, TimestampMixin):
    """A user-created tracker (habit, mood, water, sleep, weight, etc.)."""

    __tablename__ = "trackers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    # tracker type: mood | habit | water | sleep | weight | workout | nutrition | gratitude | medication | custom
    tracker_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type-specific config: goal, unit, color, options, etc.
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Whether tracker is active
    is_active: Mapped[bool] = mapped_column(default=True)

    entries = relationship("TrackerEntry", back_populates="tracker", cascade="all, delete-orphan")
    user = relationship("User")


class TrackerEntry(Base, TimestampMixin):
    """A single log entry for a tracker."""

    __tablename__ = "tracker_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trackers.id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    date: Mapped[date] = mapped_column(Date, nullable=False)

    # Numeric value (mood score, weight kg, glasses of water, hours of sleep, etc.)
    value: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Flexible payload: tags, notes, sub-values (macros, sets/reps, etc.)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Optional text note
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracker = relationship("Tracker", back_populates="entries")
