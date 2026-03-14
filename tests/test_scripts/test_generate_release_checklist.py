import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.generate_release_checklist import (
    DEFAULT_QUALITY_THRESHOLDS,
    build_release_checklist,
    fetch_release_inputs,
    render_release_checklist_markdown,
    save_release_checklist,
)


async def test_fetch_release_inputs_calls_expected_endpoints():
    response_payloads = [
        {"status": "ok", "release_health": {"status": "healthy"}},
        {"switches": {"rollout_percent": 5}},
        {"next_action": "progress", "target_rollout_percent": 10},
        {"active_override": {}},
        {"review_result_size": 3, "dataset_candidate_size": 2},
        {"status": "healthy", "review_count": 4, "rates": {"task_completion_rate": 0.9}},
        {"review_queue_size": 4},
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
        "scripts.generate_release_checklist.httpx.AsyncClient",
        return_value=client_instance,
    ):
        inputs = await fetch_release_inputs(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            limit=10,
        )

    assert inputs["release_decision"]["next_action"] == "progress"
    assert inputs["review_queue"]["review_queue_size"] == 4
    assert inputs["quality_metrics"]["status"] == "healthy"
    assert client_instance.get.await_count == 7


def test_build_release_checklist_marks_ready_when_all_checks_pass():
    inputs = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "health_detailed": {
            "status": "ok",
            "release_health": {"status": "healthy", "recommended_action": "continue"},
        },
        "release_overview": {"switches": {"rollout_percent": 5}},
        "release_decision": {
            "next_action": "progress",
            "current_rollout_percent": 5,
            "target_rollout_percent": 10,
        },
        "release_overrides": {"active_override": {}},
        "weekly_curation": {
            "dataset_candidate_size": 3,
            "feedback_counts": {"helpful": 2, "unhelpful": 1},
            "review_result_size": 4,
            "review_batch_size": 1,
            "feedback_size": 3,
        },
        "quality_metrics": {
            "status": "healthy",
            "review_count": 4,
            "rates": {
                "wrong_route_rate": 0.05,
                "memory_failure_rate": 0.0,
                "tool_failure_rate": 0.0,
                "task_completion_rate": 0.8,
                "response_useful_rate": 0.9,
                "user_dissatisfaction_signal_rate": 0.25,
            },
        },
        "review_queue": {"review_queue_size": 3},
    }

    report = build_release_checklist(inputs, max_review_backlog=5)

    assert report["overall_status"] == "ready"
    assert report["quality_thresholds"]["max_wrong_route_rate"] == DEFAULT_QUALITY_THRESHOLDS[
        "max_wrong_route_rate"
    ]
    assert any(
        check["name"] == "core_services" and check["status"] == "pass"
        for check in report["checks"]
    )


def test_build_release_checklist_marks_rollback_for_failing_gates():
    inputs = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "health_detailed": {
            "status": "degraded",
            "release_health": {
                "status": "rollback_recommended",
                "recommended_action": "rollback",
            },
        },
        "release_overview": {"switches": {"rollout_percent": 25}},
        "release_decision": {
            "next_action": "rollback",
            "current_rollout_percent": 25,
            "target_rollout_percent": 0,
        },
        "release_overrides": {"active_override": {"rollout_percent": 10}},
        "weekly_curation": {
            "dataset_candidate_size": 0,
            "feedback_counts": {"helpful": 1, "unhelpful": 2},
            "review_result_size": 2,
            "review_batch_size": 1,
            "feedback_size": 3,
        },
        "quality_metrics": {
            "status": "needs_attention",
            "review_count": 5,
            "rates": {
                "wrong_route_rate": 0.4,
                "memory_failure_rate": 0.2,
                "tool_failure_rate": 0.2,
                "task_completion_rate": 0.4,
                "response_useful_rate": 0.4,
                "user_dissatisfaction_signal_rate": 0.6,
            },
        },
        "review_queue": {"review_queue_size": 40},
    }

    report = build_release_checklist(inputs, max_review_backlog=25)

    assert report["overall_status"] == "rollback"
    assert any(
        check["name"] == "rollout_decision" and check["status"] == "fail"
        for check in report["checks"]
    )


def test_render_release_checklist_markdown_includes_sections():
    report = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "overall_status": "hold",
        "checks": [
            {
                "status": "warn",
                "name": "review_backlog",
                "detail": "Backlog high.",
                "blocking": False,
            },
        ],
        "inputs": {
            "release_decision": {
                "current_rollout_percent": 10,
                "target_rollout_percent": 10,
                "next_action": "hold",
            },
            "release_overrides": {"active_override": {"rollout_percent": 10}},
            "weekly_curation": {
                "review_result_size": 5,
                "dataset_candidate_size": 2,
                "review_batch_size": 1,
                "feedback_size": 3,
            },
            "quality_metrics": {
                "status": "monitor",
                "review_count": 5,
                "rates": {
                    "wrong_route_rate": 0.2,
                    "task_completion_rate": 0.6,
                    "response_useful_rate": 0.7,
                    "user_dissatisfaction_signal_rate": 0.3,
                },
            },
        },
    }

    markdown = render_release_checklist_markdown(report)

    assert "# Release Checklist" in markdown
    assert "Overall status: HOLD" in markdown
    assert "## Weekly Analytics" in markdown
    assert "## Quality" in markdown


def test_save_release_checklist_writes_json_and_markdown(tmp_path: Path):
    report = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "overall_status": "ready",
        "checks": [],
        "inputs": {
            "release_decision": {
                "current_rollout_percent": 5,
                "target_rollout_percent": 10,
                "next_action": "progress",
            },
            "release_overrides": {"active_override": {}},
            "weekly_curation": {
                "review_result_size": 1,
                "dataset_candidate_size": 1,
                "review_batch_size": 1,
                "feedback_size": 0,
            },
            "quality_metrics": {
                "status": "healthy",
                "review_count": 1,
                "rates": {
                    "wrong_route_rate": 0.0,
                    "task_completion_rate": 1.0,
                    "response_useful_rate": 1.0,
                    "user_dissatisfaction_signal_rate": 0.0,
                },
            },
        },
    }

    paths = save_release_checklist(report, out_dir=tmp_path, prefix="release_checklist")

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["overall_status"] == "ready"
    assert "# Release Checklist" in paths["markdown"].read_text(encoding="utf-8")
