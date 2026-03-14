import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.start_controlled_canary import (
    apply_canary_override,
    build_canary_payload,
    fetch_canary_inputs,
    render_canary_report_markdown,
    save_canary_report,
    start_controlled_canary,
)


async def test_fetch_canary_inputs_calls_expected_endpoints():
    response_payloads = [
        {"switches": {"configured_cohorts": {"internal": 1, "trusted": 0, "beta": 0}}},
        {"current_rollout_percent": 0, "next_action": "progress"},
        {"status": "healthy", "rates": {"task_completion_rate": 0.9}},
    ]
    responses = []
    for payload in response_payloads:
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status = MagicMock()
        responses.append(response)

    client_instance = AsyncMock()
    client_instance.get = AsyncMock(side_effect=responses)
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    with patch(
        "scripts.start_controlled_canary.httpx.AsyncClient",
        return_value=client_instance,
    ):
        inputs = await fetch_canary_inputs(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
        )

    assert inputs["decision"]["next_action"] == "progress"
    assert inputs["quality_metrics"]["status"] == "healthy"
    assert client_instance.get.await_count == 3


def test_build_canary_payload_requires_trusted_cohorts():
    inputs = {
        "overview": {"switches": {"configured_cohorts": {"internal": 0, "trusted": 0, "beta": 0}}},
        "decision": {"current_rollout_percent": 0, "next_action": "progress"},
    }

    with pytest.raises(ValueError, match="trusted_cohorts_not_configured"):
        build_canary_payload(
            inputs,
            actor="qa-1",
            target_rollout_percent=1,
            shadow_mode=True,
            notes="start",
        )


def test_build_canary_payload_uses_progress_for_first_stage():
    inputs = {
        "overview": {"switches": {"configured_cohorts": {"internal": 1, "trusted": 1, "beta": 0}}},
        "decision": {"current_rollout_percent": 0, "next_action": "progress"},
    }

    payload = build_canary_payload(
        inputs,
        actor="qa-1",
        target_rollout_percent=1,
        shadow_mode=True,
        notes="start",
    )

    assert payload["action"] == "progress"
    assert payload["rollout_percent"] == 1
    assert payload["shadow_mode"] is True


async def test_apply_canary_override_posts_payload():
    response = MagicMock()
    response.json.return_value = {"override": {"rollout_percent": 1}}
    response.raise_for_status = MagicMock()

    client_instance = AsyncMock()
    client_instance.post = AsyncMock(return_value=response)
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = None

    payload = {"actor": "qa-1", "action": "progress", "rollout_percent": 1}
    with patch(
        "scripts.start_controlled_canary.httpx.AsyncClient",
        return_value=client_instance,
    ):
        result = await apply_canary_override(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            payload=payload,
        )

    assert result["override"]["rollout_percent"] == 1
    assert client_instance.post.await_args.kwargs["json"] == payload


def test_save_canary_report_writes_json_and_markdown(tmp_path: Path):
    report = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "applied": False,
        "payload": {"rollout_percent": 1},
        "applied_result": None,
        "inputs": {
            "decision": {"current_rollout_percent": 0, "next_action": "progress"},
            "quality_metrics": {"status": "healthy", "rates": {"task_completion_rate": 0.9}},
        },
    }

    paths = save_canary_report(report, out_dir=tmp_path, prefix="controlled_canary")

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["applied"] is False
    assert "# Controlled Canary Report" in paths["markdown"].read_text(encoding="utf-8")


async def test_start_controlled_canary_dry_run_skips_apply(tmp_path: Path):
    inputs = {
        "fetched_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "overview": {"switches": {"configured_cohorts": {"internal": 1, "trusted": 0, "beta": 0}}},
        "decision": {"current_rollout_percent": 0, "next_action": "progress"},
        "quality_metrics": {"status": "healthy", "rates": {"wrong_route_rate": 0.0}},
    }

    with (
        patch(
            "scripts.start_controlled_canary.fetch_canary_inputs",
            AsyncMock(return_value=inputs),
        ),
        patch("scripts.start_controlled_canary.apply_canary_override", AsyncMock()) as mock_apply,
    ):
        result = await start_controlled_canary(
            base_url="https://bot.example.com",
            headers={},
            actor="qa-1",
            apply=False,
            target_rollout_percent=1,
            shadow_mode=True,
            notes="start",
            out_dir=tmp_path,
            prefix="controlled_canary",
        )

    assert result["report"]["applied"] is False
    assert result["report"]["payload"]["rollout_percent"] == 1
    assert "Applied: no" in render_canary_report_markdown(result["report"])
    mock_apply.assert_not_awaited()
