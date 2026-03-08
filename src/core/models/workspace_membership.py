import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin
from src.core.models.enums import MembershipRole, MembershipStatus, MembershipType


ROLE_PRESETS: dict[str, list[str]] = {
    "owner": [
        "view_finance", "create_finance", "edit_finance", "delete_finance",
        "view_reports", "export_reports",
        "view_budgets", "manage_budgets",
        "view_work_tasks", "manage_work_tasks",
        "view_work_documents", "manage_work_documents",
        "view_contacts", "manage_contacts",
        "invite_members", "manage_members",
    ],
    "partner": [
        "view_finance", "create_finance", "edit_finance",
        "view_budgets", "manage_budgets",
        "view_reports",
    ],
    "family_member": [
        "create_finance",
        "view_budgets",
    ],
    "worker": [
        "view_work_tasks", "manage_work_tasks",
        "view_contacts",
    ],
    "assistant": [
        "view_work_tasks", "manage_work_tasks",
        "view_contacts", "manage_contacts",
        "view_work_documents",
    ],
    "accountant": [
        "view_finance", "create_finance", "edit_finance",
        "view_reports", "export_reports",
        "view_budgets", "manage_budgets",
    ],
    "viewer": [
        "view_finance", "view_reports", "view_budgets",
    ],
    "custom": [],
}


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("families.id"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"),
    )
    membership_type: Mapped[MembershipType] = mapped_column(
        ENUM(MembershipType, name="membership_type", create_type=False),
    )
    role: Mapped[MembershipRole] = mapped_column(
        ENUM(MembershipRole, name="membership_role", create_type=False),
    )
    permissions: Mapped[dict] = mapped_column(JSONB, default=list)
    status: Mapped[MembershipStatus] = mapped_column(
        ENUM(MembershipStatus, name="membership_status", create_type=False),
        default=MembershipStatus.active,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        onupdate=datetime.utcnow,
    )

    user = relationship("User", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
