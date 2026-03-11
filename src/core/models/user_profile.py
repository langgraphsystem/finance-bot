import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    timezone_source: Mapped[str] = mapped_column(String(32), default="default")
    timezone_confidence: Mapped[int] = mapped_column(Integer, default=0)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    notification_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    locale_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    occupation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tone_preference: Mapped[str] = mapped_column(String(50), default="friendly")
    response_length: Mapped[str] = mapped_column(String(20), default="concise")
    active_hours_start: Mapped[int] = mapped_column(Integer, default=8)
    active_hours_end: Mapped[int] = mapped_column(Integer, default=22)
    learned_patterns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    core_identity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User")
