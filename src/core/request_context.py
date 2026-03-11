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
_current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_request_id", default=None
)
_current_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_correlation_id", default=None
)
_current_rollout_cohort: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_rollout_cohort", default=None
)
_current_release_flags: contextvars.ContextVar[dict[str, bool] | None] = contextvars.ContextVar(
    "_current_release_flags", default=None
)


def get_current_family_id() -> str | None:
    """Return the family_id bound to the current async context, or *None*."""
    return _current_family_id.get()


def get_current_user_id() -> str | None:
    """Return the user_id bound to the current async context, or *None*."""
    return _current_user_id.get()


def get_current_request_id() -> str | None:
    """Return the request_id bound to the current async context, or *None*."""
    return _current_request_id.get()


def get_current_correlation_id() -> str | None:
    """Return the correlation_id bound to the current async context, or *None*."""
    return _current_correlation_id.get()


def get_current_rollout_cohort() -> str | None:
    """Return the rollout cohort bound to the current async context, or *None*."""
    return _current_rollout_cohort.get()


def get_current_release_flags() -> dict[str, bool] | None:
    """Return the active release flags bound to the current async context, or *None*."""
    return _current_release_flags.get()


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


class _RequestToken:
    """Holds reset tokens for request-scoped metadata."""

    __slots__ = (
        "request_token",
        "correlation_token",
        "cohort_token",
        "release_flags_token",
    )

    def __init__(
        self,
        request_token: contextvars.Token[str | None],
        correlation_token: contextvars.Token[str | None],
        cohort_token: contextvars.Token[str | None],
        release_flags_token: contextvars.Token[dict[str, bool] | None],
    ):
        self.request_token = request_token
        self.correlation_token = correlation_token
        self.cohort_token = cohort_token
        self.release_flags_token = release_flags_token


def set_request_context(
    *,
    request_id: str,
    correlation_id: str,
    rollout_cohort: str | None = None,
    release_flags: dict[str, bool] | None = None,
) -> _RequestToken:
    """Bind request-scoped metadata for the current async context."""
    rt = _current_request_id.set(request_id)
    ct = _current_correlation_id.set(correlation_id)
    cohort_t = _current_rollout_cohort.set(rollout_cohort)
    flags_t = _current_release_flags.set(release_flags)
    return _RequestToken(rt, ct, cohort_t, flags_t)


def update_request_context(
    *,
    rollout_cohort: str | None = None,
    release_flags: dict[str, bool] | None = None,
) -> None:
    """Update request-scoped rollout metadata for the current async context."""
    if rollout_cohort is not None:
        _current_rollout_cohort.set(rollout_cohort)
    if release_flags is not None:
        _current_release_flags.set(release_flags)


def reset_request_context(token: _RequestToken) -> None:
    """Restore the previous request-scoped metadata using a token."""
    _current_request_id.reset(token.request_token)
    _current_correlation_id.reset(token.correlation_token)
    _current_rollout_cohort.reset(token.cohort_token)
    _current_release_flags.reset(token.release_flags_token)
