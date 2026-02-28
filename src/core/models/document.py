import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import DocumentType


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    type: Mapped[DocumentType] = mapped_column(
        ENUM(DocumentType, name="document_type", create_type=False)
    )
    storage_path: Mapped[str] = mapped_column(Text)
    ocr_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ocr_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ocr_parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    ocr_fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Document agent extensions
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_documents_family_id", "family_id"),
        Index("ix_documents_type", "type"),
        Index("ix_documents_content_hash", "content_hash"),
    )
