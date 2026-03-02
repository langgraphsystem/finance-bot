"""SheetSyncConfig model for Google Sheets sync."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base


class SheetSyncConfig(Base):
    __tablename__ = "sheet_sync_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    spreadsheet_id: Mapped[str] = mapped_column(String, nullable=False)
    sheet_name: Mapped[str] = mapped_column(String, default="Expenses")
    sync_scope: Mapped[str] = mapped_column(String, default="expenses")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("now()"), nullable=False
    )
