import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.preflight_release_ops import (
    build_preflight_report,
    collect_env_snapshot,
    fetch_endpoint_snapshot,
    run_preflight,
    save_preflight_report,
)


def test_collect_env_snapshot_returns_release_keys():
    snapshot = collect_env_snapshot(
        {
            "APP_ENV": "production",
            "HEALTH_SECRET": "secret",
            "RELEASE_ROLLOUT_NAME": "canary-a",
            "RELEASE_OPS_ENABLED": "true",
            "RELEASE_OPS_BASE_URL": "https://bot.example.com",
            "RELEASE_INTERNAL_USER_IDS": "1,2",
        }
    )

    assert snapshot["APP_ENV"] == "production"
    assert snapshot["RELEASE_INTERNAL_USER_IDS"] == "1,2"
    assert "RELEASE_TRUSTED_USER_IDS" in snapshot


async def test_fetch_endpoint_snapshot_calls_expected_endpoints():
    payloads = [
        {"status": "ok"},
        {"switches": {"rollout_percent": 0}},
        {"next_action": "progress"},
    ]
    responses = []
    for payload in payloads:
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status = MagicMock()
        responses.append(response)

    client_instance = AsyncMock()
    client_instance.get = AsyncMock(side_effect=responses)
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    with patch(
        "scripts.preflight_release_ops.httpx.AsyncClient",
        return_value=client_instance,
    ):
        snapshot = await fetch_endpoint_snapshot(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
        )

    assert snapshot["release_decision"]["next_action"] == "progress"
    assert client_instance.get.await_count == 3


def test_build_preflight_report_marks_not_ready_when_env_missing():
    report = build_preflight_report(
        env_snapshot={
            "APP_ENV": "",
            "HEALTH_SECRET": "",
            "RELEASE_ROLLOUT_NAME": "",
            "RELEASE_OPS_ENABLED": "",
            "RELEASE_OPS_BASE_URL": "",
            "RELEASE_INTERNAL_USER_IDS": "",
            "RELEASE_TRUSTED_USER_IDS": "",
            "RELEASE_BETA_USER_IDS": "",
            "RELEASE_SHADOW_MODE": "",
        },
        base_url="https://bot.example.com",
        endpoint_error="connection failed",
    )

    assert report["overall_status"] == "not_ready"
    assert any(check["name"] == "required_env" for check in report["checks"])


def test_save_preflight_report_writes_json_and_markdown(tmp_path: Path):
    report = {
        "generated_at": "2026-03-14T00:00:00",
        "base_url": "https://bot.example.com",
        "overall_status": "ready",
        "checks": [{"status": "pass", "name": "required_env", "detail": "ok"}],
        "env_snapshot": {},
        "endpoint_snapshot": None,
        "endpoint_error": None,
    }

    paths = save_preflight_report(report, out_dir=tmp_path, prefix="release_ops_preflight")

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["overall_status"] == "ready"
    assert "# Release Ops Preflight" in paths["markdown"].read_text(encoding="utf-8")


async def test_run_preflight_skips_endpoint_when_disabled(tmp_path: Path):
    result = await run_preflight(
        base_url="https://bot.example.com",
        headers={},
        check_endpoint=False,
        out_dir=tmp_path,
        prefix="release_ops_preflight",
        env={
            "APP_ENV": "production",
            "HEALTH_SECRET": "secret",
            "RELEASE_ROLLOUT_NAME": "canary-a",
            "RELEASE_OPS_ENABLED": "true",
            "RELEASE_OPS_BASE_URL": "https://bot.example.com",
            "RELEASE_INTERNAL_USER_IDS": "1,2",
            "RELEASE_TRUSTED_USER_IDS": "",
            "RELEASE_BETA_USER_IDS": "",
            "RELEASE_SHADOW_MODE": "true",
        },
    )

    assert result["report"]["overall_status"] == "partial"
    assert result["report"]["endpoint_error"] is None
