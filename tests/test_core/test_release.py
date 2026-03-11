from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.release import (
    get_release_flag_snapshot,
    get_release_health_snapshot,
    record_release_event,
    resolve_release_cohort,
)


def _context(*, user_id: str = "u-1", role: str = "member") -> SessionContext:
    return SessionContext(
        user_id=user_id,
        family_id="f-1",
        role=role,
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


def test_release_flag_snapshot_contains_ff_flags():
    snapshot = get_release_flag_snapshot()

    assert "ff_post_gen_check" in snapshot
    assert "release_shadow_mode" in snapshot
    assert isinstance(snapshot["ff_post_gen_check"], bool)


def test_resolve_release_cohort_prefers_explicit_user_lists(monkeypatch):
    monkeypatch.setattr("src.core.release.settings.release_internal_user_ids", "u-internal")
    monkeypatch.setattr("src.core.release.settings.release_trusted_user_ids", "u-trusted")
    monkeypatch.setattr("src.core.release.settings.release_beta_user_ids", "u-beta")
    monkeypatch.setattr("src.core.release.settings.release_vip_user_ids", "u-vip")

    assert resolve_release_cohort(_context(user_id="u-internal")) == "internal"
    assert resolve_release_cohort(_context(user_id="u-trusted")) == "trusted"
    assert resolve_release_cohort(_context(user_id="u-beta")) == "beta"
    assert resolve_release_cohort(_context(user_id="u-vip")) == "vip"


def test_resolve_release_cohort_uses_sensitive_role_then_default(monkeypatch):
    monkeypatch.setattr("src.core.release.settings.release_sensitive_roles", "accountant,assistant")
    monkeypatch.setattr("src.core.release.settings.release_default_cohort", "normal")

    assert resolve_release_cohort(_context(role="accountant")) == "sensitive"
    assert resolve_release_cohort(_context(role="member")) == "normal"
    assert resolve_release_cohort(None) == "new_user"


async def test_record_release_event_updates_redis():
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.hincrby = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()

        await record_release_event("requests_total")

    mock_redis.hincrby.assert_awaited_once()
    mock_redis.hset.assert_awaited_once()
    mock_redis.expire.assert_awaited_once()


async def test_release_health_snapshot_rolls_back_when_thresholds_exceeded():
    metrics = {
        "rollout_name": "canary-a",
        "rollout_percent": "5",
        "shadow_mode": "0",
        "requests_total": "100",
        "completed_total": "90",
        "errors_total": "8",
        "no_reply_total": "3",
        "rate_limited_total": "1",
    }
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.hgetall = AsyncMock(return_value=metrics)
        snapshot = await get_release_health_snapshot()

    assert snapshot["status"] == "rollback_recommended"
    assert snapshot["recommended_action"] == "rollback"
    assert snapshot["rates"]["error_rate"] == 0.08
