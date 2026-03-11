"""Release rollout helpers for cohorts, flags, and structured lifecycle logs."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.config import settings
from src.core.context import SessionContext
from src.core.request_context import (
    get_current_correlation_id,
    get_current_release_flags,
    get_current_request_id,
    get_current_rollout_cohort,
)


def _parse_csv(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def get_release_flag_snapshot() -> dict[str, bool]:
    """Return a stable snapshot of currently active release flags."""
    data = settings.model_dump()
    snapshot = {
        key: value
        for key, value in data.items()
        if key.startswith("ff_") and isinstance(value, bool)
    }
    snapshot["release_health_logging"] = settings.release_health_logging
    snapshot["release_shadow_mode"] = settings.release_shadow_mode
    return dict(sorted(snapshot.items()))


def get_release_runtime_state() -> dict[str, Any]:
    """Return compact release metadata for structured logs."""
    return {
        "rollout_name": settings.release_rollout_name or "default",
        "rollout_percent": settings.release_rollout_percent,
        "shadow_mode": settings.release_shadow_mode,
    }


def resolve_release_cohort(context: SessionContext | None) -> str:
    """Assign a rollout cohort for the current user/context."""
    if context is None:
        return "new_user"

    user_id = str(context.user_id)
    if user_id in _parse_csv(settings.release_internal_user_ids):
        return "internal"
    if user_id in _parse_csv(settings.release_trusted_user_ids):
        return "trusted"
    if user_id in _parse_csv(settings.release_beta_user_ids):
        return "beta"
    if user_id in _parse_csv(settings.release_vip_user_ids):
        return "vip"
    if context.role in _parse_csv(settings.release_sensitive_roles):
        return "sensitive"
    return settings.release_default_cohort


def build_log_context(**fields: Any) -> dict[str, Any]:
    """Build structured log context with request and rollout metadata."""
    payload: dict[str, Any] = {
        "request_id": get_current_request_id(),
        "correlation_id": get_current_correlation_id(),
        "rollout_cohort": get_current_rollout_cohort(),
        "release_flags": get_current_release_flags(),
        **get_release_runtime_state(),
    }
    payload.update(fields)
    return payload


def log_runtime_event(logger: logging.Logger, level: str, event: str, **fields: Any) -> None:
    """Emit a single structured runtime event without requiring a custom formatter."""
    payload = build_log_context(event=event, **fields)
    rendered = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    getattr(logger, level)("%s", rendered)
