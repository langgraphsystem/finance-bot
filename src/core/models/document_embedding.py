"""SQLAlchemy model for document_embeddings — chunked vector search.

NOTE: The `embedding` column uses pgvector's vector(1536) type. Since the
pgvector Python package may not be installed locally, we use raw SQL for
vector operations (insert, query). This model is used for non-vector
operations (delete, basic selects).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    chunk_text: Mapped[str] = mapped_column(Text)
    # embedding: vector(1536) — handled via raw SQL, not mapped here
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
