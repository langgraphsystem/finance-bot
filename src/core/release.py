"""Release rollout helpers for cohorts, flags, and structured lifecycle logs."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import redis
from src.core.request_context import (
    get_current_correlation_id,
    get_current_release_enabled,
    get_current_release_flags,
    get_current_release_mode,
    get_current_request_id,
    get_current_rollout_bucket,
    get_current_rollout_cohort,
    get_current_shadow_enabled,
)

_RELEASE_HEALTH_TTL_SECONDS = 86400
_ALWAYS_ON_COHORTS = {"internal", "trusted", "beta"}
_PROTECTED_COHORTS = {"sensitive", "vip", "new_user"}
_ROLLOUT_PROGRESS_STEPS = (1, 5, 10, 25, 50, 100)
_RELEASE_OVERRIDE_KEY_PREFIX = "release_override"
_RELEASE_ACTIONS_KEY_PREFIX = "release_actions"
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


def _release_override_key() -> str:
    rollout_name = settings.release_rollout_name or "default"
    return f"{_RELEASE_OVERRIDE_KEY_PREFIX}:{rollout_name}"


def _release_actions_key() -> str:
    rollout_name = settings.release_rollout_name or "default"
    return f"{_RELEASE_ACTIONS_KEY_PREFIX}:{rollout_name}"


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_rollout_percent(value: Any, *, fallback: int) -> int:
    try:
        rollout_percent = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, min(rollout_percent, 100))


def _merge_runtime_state(
    base_state: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(base_state)
    normalized_override = dict(override or {})
    if normalized_override:
        merged["rollout_percent"] = _coerce_rollout_percent(
            normalized_override.get("rollout_percent"),
            fallback=base_state["rollout_percent"],
        )
        merged["shadow_mode"] = _parse_bool(
            normalized_override.get("shadow_mode"),
            default=base_state["shadow_mode"],
        )
    merged["override_active"] = bool(normalized_override)
    return merged


async def get_release_override() -> dict[str, Any]:
    """Return the active operator override for the current rollout, if any."""
    try:
        raw = await redis.get(_release_override_key())
    except Exception:
        logger.debug("Release override fetch failed", exc_info=True)
        return {}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


async def get_effective_release_runtime_state() -> dict[str, Any]:
    """Return rollout runtime state with operator overrides applied."""
    return _merge_runtime_state(
        get_release_runtime_state(),
        await get_release_override(),
    )


def get_release_switches() -> dict[str, Any]:
    """Return operator-facing rollout switches without exposing raw user IDs."""
    return {
        **get_release_runtime_state(),
        "health_logging": settings.release_health_logging,
        "default_cohort": settings.release_default_cohort,
        "configured_cohorts": {
            "internal": len(_parse_csv(settings.release_internal_user_ids)),
            "trusted": len(_parse_csv(settings.release_trusted_user_ids)),
            "beta": len(_parse_csv(settings.release_beta_user_ids)),
            "vip": len(_parse_csv(settings.release_vip_user_ids)),
            "sensitive_roles": sorted(_parse_csv(settings.release_sensitive_roles)),
        },
    }


async def get_effective_release_switches() -> dict[str, Any]:
    """Return operator-facing rollout switches with effective overrides applied."""
    effective_runtime = await get_effective_release_runtime_state()
    switches = get_release_switches()
    switches.update(
        {
            "rollout_percent": effective_runtime["rollout_percent"],
            "shadow_mode": effective_runtime["shadow_mode"],
            "override_active": effective_runtime["override_active"],
        }
    )
    return switches


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
        "rollout_bucket": get_current_rollout_bucket(),
        "release_mode": get_current_release_mode(),
        "release_enabled": get_current_release_enabled(),
        "shadow_enabled": get_current_shadow_enabled(),
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
        effective_runtime = await get_effective_release_runtime_state()
        key = _release_health_key()
        await redis.hincrby(key, event, increment)
        await redis.hset(
            key,
            mapping={
                "rollout_name": effective_runtime["rollout_name"],
                "rollout_percent": effective_runtime["rollout_percent"],
                "shadow_mode": int(effective_runtime["shadow_mode"]),
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


def _stable_rollout_bucket(subject_id: str) -> int:
    """Assign a deterministic rollout bucket in the range [0, 99]."""
    rollout_name = settings.release_rollout_name or "default"
    digest = hashlib.sha256(f"{rollout_name}:{subject_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def _next_rollout_percent(current_percent: int) -> int:
    """Return the next progressive rollout step."""
    for step in _ROLLOUT_PROGRESS_STEPS:
        if step > current_percent:
            return step
    return 100


async def get_release_health_snapshot() -> dict[str, Any]:
    """Return a compact rollout health snapshot based on recent counters."""
    if not settings.release_health_logging:
        return {
            "status": "disabled",
            "recommended_action": "ignore",
            "rollout_name": settings.release_rollout_name or "default",
        }
    effective_runtime = await get_effective_release_runtime_state()

    try:
        metrics = await redis.hgetall(_release_health_key())
    except Exception:
        logger.debug("Release health snapshot unavailable", exc_info=True)
        return {
            "status": "unavailable",
            "recommended_action": "ignore",
            "rollout_name": effective_runtime["rollout_name"],
            "rollout_percent": effective_runtime["rollout_percent"],
            "shadow_mode": effective_runtime["shadow_mode"],
            "override_active": effective_runtime["override_active"],
        }
    requests_total = _parse_int(metrics, "requests_total")
    completed_total = _parse_int(metrics, "completed_total")
    errors_total = _parse_int(metrics, "errors_total")
    no_reply_total = _parse_int(metrics, "no_reply_total")
    rate_limited_total = _parse_int(metrics, "rate_limited_total")
    shadow_requests_total = _parse_int(metrics, "shadow_requests_total")
    shadow_match_total = _parse_int(metrics, "shadow_match_total")
    shadow_mismatch_total = _parse_int(metrics, "shadow_mismatch_total")
    shadow_route_match_total = _parse_int(metrics, "shadow_route_match_total")
    shadow_route_mismatch_total = _parse_int(metrics, "shadow_route_mismatch_total")
    shadow_compare_failed_total = _parse_int(metrics, "shadow_compare_failed_total")
    shadow_compared_total = shadow_match_total + shadow_mismatch_total
    shadow_route_compared_total = shadow_route_match_total + shadow_route_mismatch_total

    error_rate = _safe_rate(errors_total, requests_total)
    no_reply_rate = _safe_rate(no_reply_total, completed_total)
    rate_limited_rate = _safe_rate(rate_limited_total, requests_total)
    shadow_request_rate = _safe_rate(shadow_requests_total, requests_total)
    shadow_mismatch_rate = _safe_rate(shadow_mismatch_total, shadow_compared_total)
    shadow_route_mismatch_rate = _safe_rate(
        shadow_route_mismatch_total,
        shadow_route_compared_total,
    )
    shadow_compare_failure_rate = _safe_rate(
        shadow_compare_failed_total,
        shadow_requests_total or (shadow_compared_total + shadow_compare_failed_total),
    )

    status = "healthy"
    recommended_action = "continue"
    triggered_gates: list[str] = []
    if (
        error_rate > settings.release_health_error_rate_threshold
        or no_reply_rate > settings.release_health_no_reply_rate_threshold
        or rate_limited_rate > settings.release_health_rate_limited_threshold
        or shadow_mismatch_rate > settings.release_health_shadow_mismatch_threshold
        or shadow_route_mismatch_rate > settings.release_health_shadow_route_mismatch_threshold
        or shadow_compare_failure_rate > settings.release_health_shadow_compare_failure_threshold
    ):
        status = "rollback_recommended"
        recommended_action = "rollback"
    elif (
        errors_total
        or no_reply_total
        or rate_limited_total
        or shadow_mismatch_total
        or shadow_route_mismatch_total
        or shadow_compare_failed_total
    ):
        status = "degraded"
        recommended_action = "hold"

    if error_rate > settings.release_health_error_rate_threshold:
        triggered_gates.append("error_rate")
    if no_reply_rate > settings.release_health_no_reply_rate_threshold:
        triggered_gates.append("no_reply_rate")
    if rate_limited_rate > settings.release_health_rate_limited_threshold:
        triggered_gates.append("rate_limited_rate")
    if shadow_mismatch_rate > settings.release_health_shadow_mismatch_threshold:
        triggered_gates.append("shadow_mismatch_rate")
    if shadow_route_mismatch_rate > settings.release_health_shadow_route_mismatch_threshold:
        triggered_gates.append("shadow_route_mismatch_rate")
    if shadow_compare_failure_rate > settings.release_health_shadow_compare_failure_threshold:
        triggered_gates.append("shadow_compare_failure_rate")

    return {
        "status": status,
        "recommended_action": recommended_action,
        "rollout_name": metrics.get("rollout_name", effective_runtime["rollout_name"]),
        "rollout_percent": _coerce_rollout_percent(
            metrics.get("rollout_percent"),
            fallback=effective_runtime["rollout_percent"],
        ),
        "shadow_mode": _parse_bool(
            metrics.get("shadow_mode"),
            default=effective_runtime["shadow_mode"],
        ),
        "override_active": effective_runtime["override_active"],
        "counts": {
            "requests_total": requests_total,
            "completed_total": completed_total,
            "errors_total": errors_total,
            "no_reply_total": no_reply_total,
            "rate_limited_total": rate_limited_total,
            "shadow_requests_total": shadow_requests_total,
            "shadow_match_total": shadow_match_total,
            "shadow_mismatch_total": shadow_mismatch_total,
            "shadow_route_match_total": shadow_route_match_total,
            "shadow_route_mismatch_total": shadow_route_mismatch_total,
            "shadow_compare_failed_total": shadow_compare_failed_total,
        },
        "rates": {
            "error_rate": error_rate,
            "no_reply_rate": no_reply_rate,
            "rate_limited_rate": rate_limited_rate,
            "shadow_request_rate": shadow_request_rate,
            "shadow_mismatch_rate": shadow_mismatch_rate,
            "shadow_route_mismatch_rate": shadow_route_mismatch_rate,
            "shadow_compare_failure_rate": shadow_compare_failure_rate,
        },
        "thresholds": {
            "error_rate": settings.release_health_error_rate_threshold,
            "no_reply_rate": settings.release_health_no_reply_rate_threshold,
            "rate_limited_rate": settings.release_health_rate_limited_threshold,
            "shadow_mismatch_rate": settings.release_health_shadow_mismatch_threshold,
            "shadow_route_mismatch_rate": settings.release_health_shadow_route_mismatch_threshold,
            "shadow_compare_failure_rate": settings.release_health_shadow_compare_failure_threshold,
        },
        "gates": {
            "passed": not triggered_gates,
            "triggered": triggered_gates,
        },
    }


async def get_release_request_plan(
    context: SessionContext | None,
    *,
    subject_id: str | None = None,
) -> dict[str, Any]:
    """Return the rollout decision for a specific request."""
    cohort = resolve_release_cohort(context)
    stable_subject = (
        subject_id
        or (str(context.user_id) if context else None)
        or get_current_correlation_id()
        or "anonymous"
    )
    bucket = _stable_rollout_bucket(stable_subject)
    health = await get_release_health_snapshot()
    effective_runtime = await get_effective_release_runtime_state()
    rollout_percent = int(effective_runtime["rollout_percent"])

    release_enabled = False
    mode = "control"
    if health.get("recommended_action") == "rollback":
        mode = "rollback_hold"
    elif cohort in _ALWAYS_ON_COHORTS:
        release_enabled = True
        mode = cohort
    elif cohort in _PROTECTED_COHORTS and rollout_percent < 100:
        mode = "protected"
    elif bucket < rollout_percent:
        release_enabled = True
        mode = "canary"

    shadow_enabled = bool(
        effective_runtime["shadow_mode"] and health.get("recommended_action") != "rollback"
    )

    return {
        "cohort": cohort,
        "bucket": bucket,
        "mode": mode,
        "release_enabled": release_enabled,
        "shadow_enabled": shadow_enabled,
        "rollout_percent": rollout_percent,
        "health_status": health.get("status", "unavailable"),
        "recommended_action": health.get("recommended_action", "ignore"),
        "override_active": effective_runtime["override_active"],
    }


async def get_release_rollout_decision() -> dict[str, Any]:
    """Return operator-facing rollout guidance for progress, hold, or rollback."""
    health = await get_release_health_snapshot()
    effective_runtime = await get_effective_release_runtime_state()
    current_percent = int(effective_runtime["rollout_percent"])
    if health.get("recommended_action") == "rollback":
        target_percent = 0
        next_action = "rollback"
    elif health.get("recommended_action") == "hold":
        target_percent = current_percent
        next_action = "hold"
    else:
        target_percent = _next_rollout_percent(current_percent)
        next_action = "progress" if target_percent > current_percent else "hold"

    reasons = health.get("gates", {}).get("triggered", [])
    if not reasons and health.get("status") == "degraded":
        reasons = ["non_zero_error_signals"]

    return {
        "rollout_name": settings.release_rollout_name or "default",
        "current_rollout_percent": current_percent,
        "target_rollout_percent": target_percent,
        "next_action": next_action,
        "health_status": health.get("status", "unavailable"),
        "recommended_action": health.get("recommended_action", "ignore"),
        "reasons": reasons,
        "allowed_actions": (
            ["progress", "hold", "rollback", "set", "clear"]
            if next_action == "progress"
            else ["hold", "rollback", "set", "clear"]
        ),
        "shadow_mode": effective_runtime["shadow_mode"],
        "override_active": effective_runtime["override_active"],
    }


async def _record_release_action(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    await redis.lpush(_release_actions_key(), serialized)
    await redis.ltrim(_release_actions_key(), 0, max(settings.release_action_history_limit - 1, 0))


async def get_release_action_history(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent rollout control actions for audit/review."""
    try:
        items = await redis.lrange(_release_actions_key(), 0, max(limit - 1, 0))
    except Exception:
        logger.debug("Release action history unavailable", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


async def apply_release_override(
    *,
    actor: str,
    action: str,
    rollout_percent: int | None = None,
    shadow_mode: bool | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Apply a rollout override for operator-driven canary control."""
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("actor_required")

    normalized_action = action.strip().lower()
    if normalized_action not in {"progress", "hold", "rollback", "set", "clear"}:
        raise ValueError("invalid_release_action")

    base_runtime = get_release_runtime_state()
    current_runtime = await get_effective_release_runtime_state()
    current_percent = int(current_runtime["rollout_percent"])
    current_shadow_mode = bool(current_runtime["shadow_mode"])

    if normalized_action == "clear":
        override_payload: dict[str, Any] = {}
        target_percent = base_runtime["rollout_percent"]
        target_shadow_mode = base_runtime["shadow_mode"]
        await redis.delete(_release_override_key())
    else:
        if normalized_action == "rollback":
            target_percent = 0
            target_shadow_mode = False if shadow_mode is None else shadow_mode
        elif normalized_action == "hold":
            target_percent = current_percent
            target_shadow_mode = current_shadow_mode if shadow_mode is None else shadow_mode
        elif normalized_action == "progress":
            target_percent = (
                _coerce_rollout_percent(
                    rollout_percent,
                    fallback=_next_rollout_percent(current_percent),
                )
                if rollout_percent is not None
                else _next_rollout_percent(current_percent)
            )
            target_shadow_mode = current_shadow_mode if shadow_mode is None else shadow_mode
            if target_percent < current_percent:
                raise ValueError("progress_cannot_reduce_rollout")
        else:
            if rollout_percent is None and shadow_mode is None:
                raise ValueError("override_values_required")
            target_percent = _coerce_rollout_percent(rollout_percent, fallback=current_percent)
            target_shadow_mode = current_shadow_mode if shadow_mode is None else shadow_mode

        override_payload = {
            "rollout_name": base_runtime["rollout_name"],
            "rollout_percent": target_percent,
            "shadow_mode": bool(target_shadow_mode),
            "action": normalized_action,
            "actor": normalized_actor,
            "notes": notes.strip(),
            "applied_at": datetime.now(UTC).isoformat(),
        }
        await redis.set(
            _release_override_key(),
            json.dumps(override_payload, ensure_ascii=False, default=str),
        )

    await redis.hset(
        _release_health_key(),
        mapping={
            "rollout_name": base_runtime["rollout_name"],
            "rollout_percent": target_percent,
            "shadow_mode": int(target_shadow_mode),
        },
    )
    await redis.expire(_release_health_key(), _RELEASE_HEALTH_TTL_SECONDS)

    action_record = {
        "rollout_name": base_runtime["rollout_name"],
        "actor": normalized_actor,
        "action": normalized_action,
        "rollout_percent": target_percent,
        "shadow_mode": bool(target_shadow_mode),
        "notes": notes.strip(),
        "applied_at": datetime.now(UTC).isoformat(),
        "override_active": bool(override_payload),
    }
    await _record_release_action(action_record)

    return {
        "override": override_payload,
        "effective_runtime": _merge_runtime_state(base_runtime, override_payload),
        "decision": await get_release_rollout_decision(),
    }


async def get_release_override_snapshot(limit: int = 25) -> dict[str, Any]:
    """Return the active override and recent control actions for operators."""
    override = await get_release_override()
    return {
        "active_override": override,
        "history_limit": settings.release_action_history_limit,
        "action_history": await get_release_action_history(limit=limit),
        "effective_runtime": await get_effective_release_runtime_state(),
    }


async def get_release_ops_overview() -> dict[str, Any]:
    """Return a compact operator-facing release overview."""
    return {
        "switches": await get_effective_release_switches(),
        "flags": get_release_flag_snapshot(),
        "health": await get_release_health_snapshot(),
        "decision": await get_release_rollout_decision(),
        "override": await get_release_override_snapshot(limit=10),
    }
