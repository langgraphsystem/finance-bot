from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from src.core.profiles import ProfileConfig


@dataclass
class SessionContext:
    """Isolated context for each request.
    Created by middleware on message receipt.
    All skills and agents operate ONLY through this context."""

    user_id: str
    family_id: str
    role: Literal["owner", "member"]
    language: str
    currency: str
    business_type: str | None
    categories: list[dict[str, Any]]
    merchant_mappings: list[dict[str, Any]]
    profile_config: ProfileConfig | None = None

    # Multi-channel support (Phase 1+)
    channel: str = "telegram"
    channel_user_id: str | None = None
    timezone: str = "America/New_York"
    active_domain: str | None = None
    user_profile: dict[str, Any] = field(default_factory=dict)

    def can_access_transaction(self, transaction: Any) -> bool:
        """Check access to a transaction."""
        if str(transaction.family_id) != self.family_id:
            return False
        if self.role == "owner":
            return True
        return transaction.scope in ("family",)

    def can_access_scope(self, scope: str) -> bool:
        """Check if user can see data of this scope."""
        if self.role == "owner":
            return True
        return scope == "family"

    def get_visible_scopes(self) -> list[str]:
        """Return list of scopes visible to this user."""
        if self.role == "owner":
            return ["business", "family", "personal"]
        return ["family"]

    def filter_query(self, stmt, model):
        """Add family_id and scope filters to a SQLAlchemy select."""
        import uuid

        stmt = stmt.where(model.family_id == uuid.UUID(self.family_id))
        if self.role != "owner":
            stmt = stmt.where(model.scope.in_(self.get_visible_scopes()))
        return stmt
