from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.core.models.enums import ResourceVisibility, Scope

_ROLE_VISIBLE_SCOPES: dict[str, tuple[Scope, ...]] = {
    "owner": (Scope.business, Scope.family, Scope.personal),
    "partner": (Scope.business, Scope.family),
    "viewer": (Scope.business, Scope.family),
    "worker": (Scope.business,),
    "assistant": (Scope.business,),
    "accountant": (Scope.business,),
    "family_member": (Scope.family,),
    "member": (Scope.family,),
    "custom": (Scope.family,),
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


_SCOPE_TO_VISIBILITY: dict[Scope, ResourceVisibility] = {
    Scope.personal: ResourceVisibility.private_user,
    Scope.family: ResourceVisibility.family_shared,
    Scope.business: ResourceVisibility.work_shared,
}

_ROLE_VISIBLE_VISIBILITY: dict[str, set[str]] = {
    "owner": {"private_user", "family_shared", "work_shared"},
    "partner": {"family_shared", "work_shared"},
    "family_member": {"family_shared"},
    "worker": {"work_shared"},
    "assistant": {"work_shared"},
    "accountant": {"work_shared"},
    "viewer": {"family_shared", "work_shared"},
    "member": {"family_shared"},
}


def get_default_visibility(scope: Scope) -> ResourceVisibility:
    """Map a transaction scope to a resource visibility."""
    return _SCOPE_TO_VISIBILITY.get(scope, ResourceVisibility.private_user)


def can_view_visibility(
    role: str,
    visibility: ResourceVisibility | str,
    ownership: str = "self",
) -> bool:
    """Check whether a role can view a resource with given visibility.

    ownership: "self" = resource belongs to current user, "other" = another user's.
    private_user is only visible to the resource owner regardless of role.
    """
    vis = visibility if isinstance(visibility, str) else visibility.value

    if vis == "private_user":
        return ownership == "self"

    allowed = _ROLE_VISIBLE_VISIBILITY.get(role, set())
    return vis in allowed


def apply_visibility_filter(stmt: Any, model: Any, role: str, user_id: str) -> Any:
    """Restrict a SQLAlchemy statement by visibility + user_id.

    Rules:
    - private_user: only visible to the owning user
    - family_shared / work_shared: visible based on role
    - NULL visibility (legacy rows): fall back to scope or user_id
    """
    import uuid as _uuid

    from sqlalchemy import or_

    allowed_vis = _ROLE_VISIBLE_VISIBILITY.get(role, set())
    user_uuid = None
    if user_id:
        try:
            user_uuid = _uuid.UUID(user_id)
        except (ValueError, AttributeError):
            user_uuid = None

    conditions = []
    if user_uuid is not None:
        conditions.append((model.visibility == "private_user") & (model.user_id == user_uuid))

    for vis in allowed_vis:
        if vis != "private_user":
            conditions.append(model.visibility == vis)

    if hasattr(model, "scope"):
        visible_scopes = get_visible_scopes(role)
        conditions.append(
            (model.visibility.is_(None)) & (model.scope.in_(visible_scopes))
        )
    elif user_uuid is not None:
        conditions.append(
            (model.visibility.is_(None)) & (model.user_id == user_uuid)
        )

    if not conditions:
        # No valid conditions means no access at all
        conditions.append(model.visibility == "__impossible__")

    return stmt.where(or_(*conditions))
