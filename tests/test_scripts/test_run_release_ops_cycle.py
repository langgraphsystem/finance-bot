import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.run_release_ops_cycle import (
    build_release_summary,
    get_exit_code,
    render_release_summary_markdown,
    run_release_ops_cycle,
    save_release_ops_report,
    save_release_summary,
)


def test_get_exit_code_maps_release_statuses():
    assert get_exit_code("ready") == 0
    assert get_exit_code("hold") == 2
    assert get_exit_code("rollback") == 3
    assert get_exit_code("unknown") == 1


def test_save_release_ops_report_writes_json(tmp_path: Path):
    report = {
        "overall_status": "ready",
        "exit_code": 0,
    }

    path = save_release_ops_report(
        report,
        out_dir=tmp_path,
        prefix="release_ops_cycle",
    )

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["overall_status"] == "ready"


def test_save_release_summary_writes_json_and_markdown(tmp_path: Path):
    summary = {
        "overall_status": "ready",
        "exit_code": 0,
        "executed_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "rollout": {
            "current_percent": 5,
            "target_percent": 10,
            "next_action": "progress",
            "release_health_status": "healthy",
            "release_health_action": "continue",
        },
        "quality": {
            "status": "healthy",
            "review_count": 5,
            "task_completion_rate": 0.8,
            "response_useful_rate": 0.9,
            "wrong_route_rate": 0.1,
            "memory_failure_rate": 0.0,
            "tool_failure_rate": 0.0,
            "user_dissatisfaction_signal_rate": 0.2,
        },
        "weekly_cycle": {
            "selection_count": 2,
            "applied_count": 1,
            "failed_count": 0,
            "golden_dialogue_size": 3,
        },
        "blocking_issues": [],
        "warnings": [],
    }

    paths = save_release_summary(
        summary,
        out_dir=tmp_path,
        prefix="release_summary",
    )

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["overall_status"] == "ready"
    assert "# Release Summary" in paths["markdown"].read_text(encoding="utf-8")


def test_build_release_summary_extracts_concise_fields():
    cycle_report = {
        "executed_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "overall_status": "hold",
        "exit_code": 2,
        "weekly_cycle": {
            "selection_count": 3,
            "batch_result": {"applied_count": 2, "failed_count": 1},
            "export_summary": {"golden_dialogue_size": 4},
        },
        "checklist": {
            "report": {
                "checks": [
                    {
                        "status": "warn",
                        "blocking": True,
                        "detail": "Release health is degraded.",
                    },
                    {
                        "status": "fail",
                        "blocking": True,
                        "detail": "wrong_route_rate 30.00% > 20.00%",
                    },
                ],
                "inputs": {
                    "release_decision": {
                        "current_rollout_percent": 10,
                        "target_rollout_percent": 10,
                        "next_action": "hold",
                    },
                    "health_detailed": {
                        "release_health": {
                            "status": "degraded",
                            "recommended_action": "hold",
                        }
                    },
                    "quality_metrics": {
                        "status": "monitor",
                        "review_count": 5,
                        "rates": {
                            "task_completion_rate": 0.6,
                            "response_useful_rate": 0.7,
                            "wrong_route_rate": 0.3,
                            "memory_failure_rate": 0.1,
                            "tool_failure_rate": 0.1,
                            "user_dissatisfaction_signal_rate": 0.2,
                        },
                    },
                },
            }
        },
    }

    summary = build_release_summary(cycle_report)

    assert summary["overall_status"] == "hold"
    assert summary["rollout"]["next_action"] == "hold"
    assert summary["quality"]["wrong_route_rate"] == 0.3
    assert summary["blocking_issues"] == ["wrong_route_rate 30.00% > 20.00%"]
    assert "Release health is degraded." in summary["warnings"]
    assert "## Quality" in render_release_summary_markdown(summary)


async def test_run_release_ops_cycle_builds_ready_report(tmp_path: Path):
    weekly_result = {
        "report": {
            "selection": {"selected_trace_key_count": 2},
            "batch_result": {"applied_count": 2, "failed_count": 0},
            "export_summary": {"golden_dialogue_size": 3},
        },
        "report_path": tmp_path / "weekly.json",
        "export_paths": {
            "summary": tmp_path / "summary.json",
            "weekly_snapshot": tmp_path / "weekly_snapshot.json",
            "jsonl": tmp_path / "golden.jsonl",
        },
    }
    checklist_inputs = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "health_detailed": {
            "status": "ok",
            "release_health": {"status": "healthy", "recommended_action": "continue"},
        },
        "release_overview": {"switches": {"rollout_percent": 10}},
        "release_decision": {
            "next_action": "progress",
            "current_rollout_percent": 10,
            "target_rollout_percent": 25,
        },
        "release_overrides": {"active_override": {}},
        "weekly_curation": {
            "dataset_candidate_size": 2,
            "feedback_counts": {"helpful": 3, "unhelpful": 1},
            "review_result_size": 4,
            "review_batch_size": 1,
            "feedback_size": 2,
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
        "review_queue": {"review_queue_size": 2},
    }
    checklist_paths = {
        "json": tmp_path / "checklist.json",
        "markdown": tmp_path / "checklist.md",
    }
    summary_paths = {
        "json": tmp_path / "summary.json",
        "markdown": tmp_path / "summary.md",
    }
    for path in [
        weekly_result["report_path"],
        *weekly_result["export_paths"].values(),
    ]:
        path.write_text("{}", encoding="utf-8")
    for path in checklist_paths.values():
        path.write_text("{}", encoding="utf-8")
    for path in summary_paths.values():
        path.write_text("{}", encoding="utf-8")

    with (
        patch(
            "scripts.run_release_ops_cycle.run_weekly_review_cycle",
            AsyncMock(return_value=weekly_result),
        ) as mock_weekly,
        patch(
            "scripts.run_release_ops_cycle.fetch_release_inputs",
            AsyncMock(return_value=checklist_inputs),
        ) as mock_fetch,
        patch(
            "scripts.run_release_ops_cycle.save_release_checklist",
            return_value=checklist_paths,
        ),
        patch(
            "scripts.run_release_ops_cycle.save_release_summary",
            return_value=summary_paths,
        ),
    ):
        result = await run_release_ops_cycle(
            base_url="https://bot.example.com",
            headers={"Authorization": "Bearer secret"},
            reviewer="qa-1",
            apply_weekly_review=True,
            review_limit=50,
            selection_limit=100,
            max_selected=25,
            export_limit=100,
            notes="weekly review cycle",
            labels=["weekly_review"],
            review_label=None,
            suggested_action="promote_to_dataset",
            suggested_final_label=None,
            tag="golden_replay",
            source="test_bot_live_golden_replay",
            max_review_backlog=25,
            quality_thresholds={
                "max_wrong_route_rate": 0.2,
                "max_memory_failure_rate": 0.15,
                "max_tool_failure_rate": 0.15,
                "max_user_dissatisfaction_rate": 0.4,
                "min_task_completion_rate": 0.7,
                "min_response_useful_rate": 0.7,
            },
            out_dir=tmp_path,
            export_prefix="weekly_golden_dialogues",
            weekly_report_prefix="weekly_review_cycle",
            checklist_prefix="release_checklist",
            summary_prefix="release_summary",
            cycle_prefix="release_ops_cycle",
        )

    assert result["report"]["overall_status"] == "ready"
    assert result["report"]["exit_code"] == 0
    assert result["report_path"].exists()
    assert result["report"]["weekly_cycle"]["selection_count"] == 2
    assert result["report"]["summary"]["quality"]["task_completion_rate"] == 0.8
    assert result["summary_paths"]["json"] == summary_paths["json"]
    mock_weekly.assert_awaited_once()
    mock_fetch.assert_awaited_once()


async def test_run_release_ops_cycle_uses_hold_exit_code(tmp_path: Path):
    weekly_result = {
        "report": {
            "selection": {"selected_trace_key_count": 0},
            "batch_result": None,
            "export_summary": {"golden_dialogue_size": 1},
        },
        "report_path": tmp_path / "weekly.json",
        "export_paths": {
            "summary": tmp_path / "summary.json",
            "weekly_snapshot": tmp_path / "weekly_snapshot.json",
            "jsonl": tmp_path / "golden.jsonl",
        },
    }
    checklist_inputs = {
        "generated_at": "2026-03-13T00:00:00",
        "base_url": "https://bot.example.com",
        "health_detailed": {
            "status": "ok",
            "release_health": {"status": "degraded", "recommended_action": "hold"},
        },
        "release_overview": {"switches": {"rollout_percent": 25}},
        "release_decision": {
            "next_action": "hold",
            "current_rollout_percent": 25,
            "target_rollout_percent": 25,
        },
        "release_overrides": {"active_override": {}},
        "weekly_curation": {
            "dataset_candidate_size": 0,
            "feedback_counts": {"helpful": 1, "unhelpful": 1},
            "review_result_size": 1,
            "review_batch_size": 0,
            "feedback_size": 0,
        },
        "quality_metrics": {
            "status": "monitor",
            "review_count": 1,
            "rates": {
                "wrong_route_rate": 0.1,
                "memory_failure_rate": 0.0,
                "tool_failure_rate": 0.0,
                "task_completion_rate": 0.8,
                "response_useful_rate": 0.8,
                "user_dissatisfaction_signal_rate": 0.0,
            },
        },
        "review_queue": {"review_queue_size": 4},
    }
    checklist_paths = {
        "json": tmp_path / "checklist.json",
        "markdown": tmp_path / "checklist.md",
    }
    summary_paths = {
        "json": tmp_path / "summary.json",
        "markdown": tmp_path / "summary.md",
    }
    for path in [
        weekly_result["report_path"],
        *weekly_result["export_paths"].values(),
    ]:
        path.write_text("{}", encoding="utf-8")
    for path in checklist_paths.values():
        path.write_text("{}", encoding="utf-8")
    for path in summary_paths.values():
        path.write_text("{}", encoding="utf-8")

    with (
        patch(
            "scripts.run_release_ops_cycle.run_weekly_review_cycle",
            AsyncMock(return_value=weekly_result),
        ),
        patch(
            "scripts.run_release_ops_cycle.fetch_release_inputs",
            AsyncMock(return_value=checklist_inputs),
        ),
        patch(
            "scripts.run_release_ops_cycle.save_release_checklist",
            return_value=checklist_paths,
        ),
        patch(
            "scripts.run_release_ops_cycle.save_release_summary",
            return_value=summary_paths,
        ),
    ):
        result = await run_release_ops_cycle(
            base_url="https://bot.example.com",
            headers={},
            reviewer="release-ops",
            apply_weekly_review=False,
            review_limit=50,
            selection_limit=100,
            max_selected=25,
            export_limit=100,
            notes="weekly review cycle",
            labels=[],
            review_label=None,
            suggested_action="promote_to_dataset",
            suggested_final_label=None,
            tag="golden_replay",
            source="test_bot_live_golden_replay",
            max_review_backlog=25,
            quality_thresholds={
                "max_wrong_route_rate": 0.2,
                "max_memory_failure_rate": 0.15,
                "max_tool_failure_rate": 0.15,
                "max_user_dissatisfaction_rate": 0.4,
                "min_task_completion_rate": 0.7,
                "min_response_useful_rate": 0.7,
            },
            out_dir=tmp_path,
            export_prefix="weekly_golden_dialogues",
            weekly_report_prefix="weekly_review_cycle",
            checklist_prefix="release_checklist",
            summary_prefix="release_summary",
            cycle_prefix="release_ops_cycle",
        )

    assert result["report"]["overall_status"] == "hold"
    assert result["report"]["exit_code"] == 2
