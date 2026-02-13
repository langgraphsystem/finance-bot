"""Request-scoped context variables for RLS (Row Level Security).

This module is intentionally kept small and dependency-free to avoid circular
imports: both ``db.py`` and ``router.py`` import from here.
"""

from __future__ import annotations

import contextvars

_current_family_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_family_id", default=None
)


def get_current_family_id() -> str | None:
    """Return the family_id bound to the current async context, or *None*."""
    return _current_family_id.get()


def set_family_context(family_id: str) -> contextvars.Token[str | None]:
    """Set family_id for the current async context.

    Returns a reset token so the caller can restore the previous value::

        token = set_family_context(family_id)
        try:
            ...
        finally:
            reset_family_context(token)
    """
    return _current_family_id.set(family_id)


def reset_family_context(token: contextvars.Token[str | None]) -> None:
    """Restore the previous family_id value using a token from *set_family_context*."""
    _current_family_id.reset(token)
