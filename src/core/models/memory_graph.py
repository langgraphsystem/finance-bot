"""SQLAlchemy model for memory_graph — entity relationship tracking."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class MemoryGraph(Base):
    __tablename__ = "memory_graph"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[str] = mapped_column(String(255))
    relation: Mapped[str] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(50))
    object_id: Mapped[str] = mapped_column(String(255))
    strength: Mapped[float] = mapped_column(Float, default=1.0)
    graph_metadata: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
