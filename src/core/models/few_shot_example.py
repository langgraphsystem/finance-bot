"""FewShotExample model for dynamic intent detection learning."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class FewShotExample(Base):
    __tablename__ = "few_shot_examples"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_message: Mapped[str] = mapped_column(String, nullable=False)
    detected_intent: Mapped[str] = mapped_column(String, nullable=False)
    corrected_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    intent_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_score: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("now()"), nullable=False
    )
