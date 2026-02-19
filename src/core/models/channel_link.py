"""Channel link model — maps external channel user IDs to internal users."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import ChannelType


class ChannelLink(Base, TimestampMixin):
    __tablename__ = "channel_links"
    __table_args__ = (UniqueConstraint("channel", "channel_user_id", name="uq_channel_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    channel: Mapped[ChannelType] = mapped_column(
        ENUM(ChannelType, name="channel_type", create_type=False)
    )
    channel_user_id: Mapped[str] = mapped_column(String(255))
    channel_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    family = relationship("Family")
