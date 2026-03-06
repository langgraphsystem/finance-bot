from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.core.models.enums import Scope

_ROLE_VISIBLE_SCOPES: dict[str, tuple[Scope, ...]] = {
    "owner": (Scope.business, Scope.family, Scope.personal),
    "member": (Scope.family,),
}


def get_visible_scopes(role: str) -> tuple[Scope, ...]:
    """Return the scopes visible to a given role.

    Unknown roles default to the safest option: family-only access.
    """
    return _ROLE_VISIBLE_SCOPES.get(role, (Scope.family,))


def can_access_scope(role: str, scope: str | Scope) -> bool:
    """Check whether a role can access a scope."""
    try:
        normalized = scope if isinstance(scope, Scope) else Scope(scope)
    except ValueError:
        return False
    return normalized in get_visible_scopes(role)


def apply_scope_filter(stmt: Any, model: Any, role: str) -> Any:
    """Restrict a SQLAlchemy statement to scopes visible for the role."""
    if role == "owner":
        return stmt
    return stmt.where(model.scope.in_(get_visible_scopes(role)))


def filter_scope_items(items: Iterable[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    """Filter preloaded dict items by their scope key."""
    return [item for item in items if can_access_scope(role, item.get("scope", ""))]
