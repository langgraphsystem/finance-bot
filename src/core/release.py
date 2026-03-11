"""Release rollout helpers for cohorts, flags, and structured lifecycle logs."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import redis
from src.core.request_context import (
    get_current_correlation_id,
    get_current_release_flags,
    get_current_request_id,
    get_current_rollout_cohort,
)

_RELEASE_HEALTH_TTL_SECONDS = 86400
logger = logging.getLogger(__name__)


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


def _release_health_key() -> str:
    rollout_name = settings.release_rollout_name or "default"
    return f"release_health:{rollout_name}"


async def record_release_event(event: str, increment: int = 1) -> None:
    """Record a release-health counter for the active rollout."""
    if not settings.release_health_logging:
        return

    try:
        key = _release_health_key()
        await redis.hincrby(key, event, increment)
        await redis.hset(
            key,
            mapping={
                "rollout_name": settings.release_rollout_name or "default",
                "rollout_percent": settings.release_rollout_percent,
                "shadow_mode": int(settings.release_shadow_mode),
            },
        )
        await redis.expire(key, _RELEASE_HEALTH_TTL_SECONDS)
    except Exception:
        logger.debug("Release health counter update failed for %s", event, exc_info=True)


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _parse_int(metrics: dict[str, str], key: str) -> int:
    try:
        return int(metrics.get(key, "0"))
    except (TypeError, ValueError):
        return 0


async def get_release_health_snapshot() -> dict[str, Any]:
    """Return a compact rollout health snapshot based on recent counters."""
    if not settings.release_health_logging:
        return {
            "status": "disabled",
            "recommended_action": "ignore",
            "rollout_name": settings.release_rollout_name or "default",
        }

    try:
        metrics = await redis.hgetall(_release_health_key())
    except Exception:
        logger.debug("Release health snapshot unavailable", exc_info=True)
        return {
            "status": "unavailable",
            "recommended_action": "ignore",
            "rollout_name": settings.release_rollout_name or "default",
        }
    requests_total = _parse_int(metrics, "requests_total")
    completed_total = _parse_int(metrics, "completed_total")
    errors_total = _parse_int(metrics, "errors_total")
    no_reply_total = _parse_int(metrics, "no_reply_total")
    rate_limited_total = _parse_int(metrics, "rate_limited_total")

    error_rate = _safe_rate(errors_total, requests_total)
    no_reply_rate = _safe_rate(no_reply_total, completed_total)
    rate_limited_rate = _safe_rate(rate_limited_total, requests_total)

    status = "healthy"
    recommended_action = "continue"
    if (
        error_rate > settings.release_health_error_rate_threshold
        or no_reply_rate > settings.release_health_no_reply_rate_threshold
        or rate_limited_rate > settings.release_health_rate_limited_threshold
    ):
        status = "rollback_recommended"
        recommended_action = "rollback"
    elif errors_total or no_reply_total or rate_limited_total:
        status = "degraded"
        recommended_action = "hold"

    return {
        "status": status,
        "recommended_action": recommended_action,
        "rollout_name": metrics.get("rollout_name", settings.release_rollout_name or "default"),
        "rollout_percent": _parse_int(metrics, "rollout_percent"),
        "shadow_mode": bool(_parse_int(metrics, "shadow_mode")),
        "counts": {
            "requests_total": requests_total,
            "completed_total": completed_total,
            "errors_total": errors_total,
            "no_reply_total": no_reply_total,
            "rate_limited_total": rate_limited_total,
        },
        "rates": {
            "error_rate": error_rate,
            "no_reply_rate": no_reply_rate,
            "rate_limited_rate": rate_limited_rate,
        },
        "thresholds": {
            "error_rate": settings.release_health_error_rate_threshold,
            "no_reply_rate": settings.release_health_no_reply_rate_threshold,
            "rate_limited_rate": settings.release_health_rate_limited_threshold,
        },
    }
