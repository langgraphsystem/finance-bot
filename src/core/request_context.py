"""Request-scoped context variables for RLS (Row Level Security).

This module is intentionally kept small and dependency-free to avoid circular
imports: both ``db.py`` and ``router.py`` import from here.
"""

from __future__ import annotations

import contextvars

_current_family_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_family_id", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)


def get_current_family_id() -> str | None:
    """Return the family_id bound to the current async context, or *None*."""
    return _current_family_id.get()


def get_current_user_id() -> str | None:
    """Return the user_id bound to the current async context, or *None*."""
    return _current_user_id.get()


class _RLSToken:
    """Holds reset tokens for both family and user context vars."""

    __slots__ = ("family_token", "user_token")

    def __init__(
        self,
        family_token: contextvars.Token[str | None],
        user_token: contextvars.Token[str | None] | None = None,
    ):
        self.family_token = family_token
        self.user_token = user_token


def set_family_context(
    family_id: str, user_id: str | None = None
) -> _RLSToken:
    """Set family_id (and optionally user_id) for the current async context.

    Returns a reset token so the caller can restore the previous values::

        token = set_family_context(family_id, user_id)
        try:
            ...
        finally:
            reset_family_context(token)
    """
    ft = _current_family_id.set(family_id)
    ut = _current_user_id.set(user_id) if user_id else None
    return _RLSToken(ft, ut)


def reset_family_context(token: _RLSToken | contextvars.Token[str | None]) -> None:
    """Restore the previous context values using a token from *set_family_context*."""
    if isinstance(token, _RLSToken):
        _current_family_id.reset(token.family_token)
        if token.user_token is not None:
            _current_user_id.reset(token.user_token)
    else:
        # Backward compat: bare contextvars.Token
        _current_family_id.reset(token)
