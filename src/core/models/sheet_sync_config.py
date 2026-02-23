import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class SheetSyncConfig(Base):
    """Google Sheets sync configuration per family."""

    __tablename__ = "sheet_sync_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("families.id"))
    spreadsheet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(64), default="Expenses")
    sync_scope: Mapped[str] = mapped_column(String(32), default="expenses")
    shared_emails: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
