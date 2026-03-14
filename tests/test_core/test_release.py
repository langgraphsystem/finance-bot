from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.release import (
    apply_release_override,
    get_effective_release_runtime_state,
    get_release_action_history,
    get_release_flag_snapshot,
    get_release_health_snapshot,
    get_release_ops_overview,
    get_release_override_snapshot,
    get_release_request_plan,
    get_release_rollout_decision,
    get_release_switches,
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
        "shadow_mode": "1",
        "requests_total": "100",
        "completed_total": "90",
        "errors_total": "8",
        "no_reply_total": "3",
        "rate_limited_total": "1",
        "shadow_requests_total": "20",
        "shadow_match_total": "10",
        "shadow_mismatch_total": "7",
        "shadow_route_match_total": "10",
        "shadow_route_mismatch_total": "5",
        "shadow_compare_failed_total": "1",
    }
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.hgetall = AsyncMock(return_value=metrics)
        snapshot = await get_release_health_snapshot()

    assert snapshot["status"] == "rollback_recommended"
    assert snapshot["recommended_action"] == "rollback"
    assert snapshot["rates"]["error_rate"] == 0.08
    assert snapshot["rates"]["shadow_request_rate"] == 0.2
    assert snapshot["rates"]["shadow_mismatch_rate"] == 0.4118
    assert snapshot["rates"]["shadow_route_mismatch_rate"] == 0.3333
    assert "shadow_mismatch_rate" in snapshot["gates"]["triggered"]
    assert "shadow_route_mismatch_rate" in snapshot["gates"]["triggered"]


async def test_effective_release_runtime_state_applies_override():
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value='{"rollout_percent":25,"shadow_mode":true}')
        state = await get_effective_release_runtime_state()

    assert state["rollout_percent"] == 25
    assert state["shadow_mode"] is True
    assert state["override_active"] is True


def test_release_switches_hide_raw_user_ids(monkeypatch):
    monkeypatch.setattr("src.core.release.settings.release_internal_user_ids", "1,2")
    monkeypatch.setattr("src.core.release.settings.release_sensitive_roles", "accountant,assistant")

    switches = get_release_switches()

    assert switches["configured_cohorts"]["internal"] == 2
    assert switches["configured_cohorts"]["sensitive_roles"] == ["accountant", "assistant"]
    assert "release_internal_user_ids" not in switches


async def test_release_ops_overview_combines_switches_flags_and_health():
    with patch(
        "src.core.release.get_release_health_snapshot",
        AsyncMock(return_value={"status": "healthy", "recommended_action": "continue"}),
    ):
        overview = await get_release_ops_overview()

    assert "switches" in overview
    assert "flags" in overview
    assert overview["health"]["status"] == "healthy"
    assert "decision" in overview
    assert "override" in overview


async def test_release_request_plan_keeps_internal_users_enabled_during_canary_hold():
    with (
        patch("src.core.release.settings.release_rollout_percent", 0),
        patch(
            "src.core.release.get_release_health_snapshot",
            AsyncMock(return_value={"status": "healthy", "recommended_action": "continue"}),
        ),
    ):
        plan = await get_release_request_plan(_context(user_id="u-1", role="member"))

    assert plan["mode"] == "control"
    assert plan["release_enabled"] is False

    with (
        patch("src.core.release.settings.release_internal_user_ids", "u-1"),
        patch("src.core.release.settings.release_rollout_percent", 0),
        patch(
            "src.core.release.get_release_health_snapshot",
            AsyncMock(return_value={"status": "healthy", "recommended_action": "continue"}),
        ),
    ):
        internal_plan = await get_release_request_plan(_context(user_id="u-1", role="member"))

    assert internal_plan["mode"] == "internal"
    assert internal_plan["release_enabled"] is True


async def test_release_request_plan_protects_sensitive_and_stops_shadow_on_rollback():
    with (
        patch("src.core.release.settings.release_rollout_percent", 50),
        patch("src.core.release.settings.release_shadow_mode", True),
        patch(
            "src.core.release.get_release_health_snapshot",
            AsyncMock(
                return_value={
                    "status": "rollback_recommended",
                    "recommended_action": "rollback",
                }
            ),
        ),
    ):
        plan = await get_release_request_plan(_context(role="accountant"))

    assert plan["mode"] == "rollback_hold"
    assert plan["release_enabled"] is False
    assert plan["shadow_enabled"] is False


async def test_release_rollout_decision_suggests_progress_when_healthy():
    with (
        patch("src.core.release.settings.release_rollout_percent", 5),
        patch(
            "src.core.release.get_release_health_snapshot",
            AsyncMock(
                return_value={
                    "status": "healthy",
                    "recommended_action": "continue",
                    "gates": {"triggered": []},
                }
            ),
        ),
    ):
        decision = await get_release_rollout_decision()

    assert decision["next_action"] == "progress"
    assert decision["target_rollout_percent"] == 10
    assert "progress" in decision["allowed_actions"]


async def test_release_rollout_decision_holds_when_degraded_without_gate_breach():
    with (
        patch("src.core.release.settings.release_rollout_percent", 10),
        patch(
            "src.core.release.get_release_health_snapshot",
            AsyncMock(
                return_value={
                    "status": "degraded",
                    "recommended_action": "hold",
                    "gates": {"triggered": []},
                }
            ),
        ),
    ):
        decision = await get_release_rollout_decision()

    assert decision["next_action"] == "hold"
    assert decision["target_rollout_percent"] == 10
    assert decision["reasons"] == ["non_zero_error_signals"]


async def test_apply_release_override_progress_records_action():
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.hgetall = AsyncMock(
            return_value={
                "rollout_name": "default",
                "rollout_percent": "25",
                "shadow_mode": "1",
                "gates": {},
            }
        )
        mock_redis.set = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        result = await apply_release_override(
            actor="qa-1",
            action="progress",
            rollout_percent=25,
            shadow_mode=True,
            notes="expand canary",
        )

    assert result["override"]["rollout_percent"] == 25
    assert result["override"]["shadow_mode"] is True
    assert result["effective_runtime"]["override_active"] is True
    mock_redis.set.assert_awaited_once()
    mock_redis.lpush.assert_awaited_once()


async def test_apply_release_override_clear_resets_to_base(monkeypatch):
    monkeypatch.setattr("src.core.release.settings.release_rollout_percent", 5)
    monkeypatch.setattr("src.core.release.settings.release_shadow_mode", False)
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value='{"rollout_percent":25,"shadow_mode":true}')
        mock_redis.hgetall = AsyncMock(
            return_value={
                "rollout_name": "default",
                "rollout_percent": "5",
                "shadow_mode": "0",
                "gates": {},
            }
        )
        mock_redis.delete = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        result = await apply_release_override(
            actor="qa-1",
            action="clear",
            notes="revert to config",
        )

    assert result["override"] == {}
    assert result["effective_runtime"]["rollout_percent"] == 5
    assert result["effective_runtime"]["override_active"] is False
    mock_redis.delete.assert_awaited_once()


async def test_get_release_action_history_and_snapshot():
    items = [
        '{"actor":"qa-1","action":"progress","rollout_percent":10}',
    ]
    with patch("src.core.release.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value='{"rollout_percent":10,"shadow_mode":false}')
        mock_redis.lrange = AsyncMock(return_value=items)
        history = await get_release_action_history(limit=1)
        snapshot = await get_release_override_snapshot(limit=1)

    assert history[0]["action"] == "progress"
    assert snapshot["active_override"]["rollout_percent"] == 10
    assert snapshot["action_history"][0]["actor"] == "qa-1"
