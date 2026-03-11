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
_current_rollout_bucket: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_current_rollout_bucket", default=None
)
_current_release_mode: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_release_mode", default=None
)
_current_release_enabled: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "_current_release_enabled", default=None
)
_current_shadow_enabled: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "_current_shadow_enabled", default=None
)
_current_request_intent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_request_intent", default=None
)
_current_analytics_tags: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "_current_analytics_tags", default=None
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


def get_current_rollout_bucket() -> int | None:
    """Return the rollout bucket bound to the current async context, or *None*."""
    return _current_rollout_bucket.get()


def get_current_release_mode() -> str | None:
    """Return the release mode bound to the current async context, or *None*."""
    return _current_release_mode.get()


def get_current_release_enabled() -> bool | None:
    """Return whether the current request is rollout-enabled, or *None*."""
    return _current_release_enabled.get()


def get_current_shadow_enabled() -> bool | None:
    """Return whether shadow evaluation is enabled for the current request."""
    return _current_shadow_enabled.get()


def get_current_request_intent() -> str | None:
    """Return the resolved request intent for the current async context."""
    return _current_request_intent.get()


def get_current_analytics_tags() -> list[str] | None:
    """Return the analytics tags for the current async context."""
    return _current_analytics_tags.get()


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
        "bucket_token",
        "mode_token",
        "release_enabled_token",
        "shadow_enabled_token",
        "intent_token",
        "analytics_tags_token",
        "release_flags_token",
    )

    def __init__(
        self,
        request_token: contextvars.Token[str | None],
        correlation_token: contextvars.Token[str | None],
        cohort_token: contextvars.Token[str | None],
        bucket_token: contextvars.Token[int | None],
        mode_token: contextvars.Token[str | None],
        release_enabled_token: contextvars.Token[bool | None],
        shadow_enabled_token: contextvars.Token[bool | None],
        intent_token: contextvars.Token[str | None],
        analytics_tags_token: contextvars.Token[list[str] | None],
        release_flags_token: contextvars.Token[dict[str, bool] | None],
    ):
        self.request_token = request_token
        self.correlation_token = correlation_token
        self.cohort_token = cohort_token
        self.bucket_token = bucket_token
        self.mode_token = mode_token
        self.release_enabled_token = release_enabled_token
        self.shadow_enabled_token = shadow_enabled_token
        self.intent_token = intent_token
        self.analytics_tags_token = analytics_tags_token
        self.release_flags_token = release_flags_token


def set_request_context(
    *,
    request_id: str,
    correlation_id: str,
    rollout_cohort: str | None = None,
    rollout_bucket: int | None = None,
    release_mode: str | None = None,
    release_enabled: bool | None = None,
    shadow_enabled: bool | None = None,
    request_intent: str | None = None,
    analytics_tags: list[str] | None = None,
    release_flags: dict[str, bool] | None = None,
) -> _RequestToken:
    """Bind request-scoped metadata for the current async context."""
    rt = _current_request_id.set(request_id)
    ct = _current_correlation_id.set(correlation_id)
    cohort_t = _current_rollout_cohort.set(rollout_cohort)
    bucket_t = _current_rollout_bucket.set(rollout_bucket)
    mode_t = _current_release_mode.set(release_mode)
    release_enabled_t = _current_release_enabled.set(release_enabled)
    shadow_enabled_t = _current_shadow_enabled.set(shadow_enabled)
    intent_t = _current_request_intent.set(request_intent)
    analytics_tags_t = _current_analytics_tags.set(analytics_tags)
    flags_t = _current_release_flags.set(release_flags)
    return _RequestToken(
        rt,
        ct,
        cohort_t,
        bucket_t,
        mode_t,
        release_enabled_t,
        shadow_enabled_t,
        intent_t,
        analytics_tags_t,
        flags_t,
    )


def update_request_context(
    *,
    rollout_cohort: str | None = None,
    rollout_bucket: int | None = None,
    release_mode: str | None = None,
    release_enabled: bool | None = None,
    shadow_enabled: bool | None = None,
    request_intent: str | None = None,
    analytics_tags: list[str] | None = None,
    release_flags: dict[str, bool] | None = None,
) -> None:
    """Update request-scoped rollout metadata for the current async context."""
    if rollout_cohort is not None:
        _current_rollout_cohort.set(rollout_cohort)
    if rollout_bucket is not None:
        _current_rollout_bucket.set(rollout_bucket)
    if release_mode is not None:
        _current_release_mode.set(release_mode)
    if release_enabled is not None:
        _current_release_enabled.set(release_enabled)
    if shadow_enabled is not None:
        _current_shadow_enabled.set(shadow_enabled)
    if request_intent is not None:
        _current_request_intent.set(request_intent)
    if analytics_tags is not None:
        _current_analytics_tags.set(analytics_tags)
    if release_flags is not None:
        _current_release_flags.set(release_flags)


def reset_request_context(token: _RequestToken) -> None:
    """Restore the previous request-scoped metadata using a token."""
    _current_request_id.reset(token.request_token)
    _current_correlation_id.reset(token.correlation_token)
    _current_rollout_cohort.reset(token.cohort_token)
    _current_rollout_bucket.reset(token.bucket_token)
    _current_release_mode.reset(token.mode_token)
    _current_release_enabled.reset(token.release_enabled_token)
    _current_shadow_enabled.reset(token.shadow_enabled_token)
    _current_request_intent.reset(token.intent_token)
    _current_analytics_tags.reset(token.analytics_tags_token)
    _current_release_flags.reset(token.release_flags_token)
