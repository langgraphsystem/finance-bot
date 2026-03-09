from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from src.core.access import apply_scope_filter, can_access_scope, get_visible_scopes

if TYPE_CHECKING:
    from src.core.profiles import ProfileConfig


ContextRole = Literal[
    "owner",
    "member",
    "partner",
    "family_member",
    "worker",
    "assistant",
    "accountant",
    "viewer",
    "custom",
]


@dataclass
class SessionContext:
    """Isolated context for each request.
    Created by middleware on message receipt.
    All skills and agents operate ONLY through this context."""

    user_id: str
    family_id: str
    role: ContextRole
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

    # RBAC Phase 1
    membership_type: str | None = None
    permissions: list[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission. Owner has all."""
        if self.role == "owner":
            return True
        return permission in self.permissions

    def can_access_transaction(self, transaction: Any) -> bool:
        """Check access to a transaction."""
        if str(transaction.family_id) != self.family_id:
            return False
        scope = getattr(transaction, "scope", None)
        if scope is None:
            return False
        return self.can_access_scope(str(scope))

    def can_access_scope(self, scope: str) -> bool:
        """Check if user can see data of this scope."""
        return can_access_scope(self.role, scope)

    def get_visible_scopes(self) -> list[str]:
        """Return list of scopes visible to this user."""
        return [scope.value for scope in get_visible_scopes(self.role)]

    def filter_query(self, stmt, model):
        """Add family_id and access filters to a SQLAlchemy select."""
        import uuid

        from src.core.access import apply_visibility_filter

        stmt = stmt.where(model.family_id == uuid.UUID(self.family_id))

        if hasattr(model, "visibility"):
            return apply_visibility_filter(stmt, model, self.role, self.user_id)
        return apply_scope_filter(stmt, model, self.role)
