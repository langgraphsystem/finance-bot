from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.core.tasks.release_ops_tasks import (
    scheduled_release_ops_cycle,
    scheduled_release_ops_weekly_review,
)


async def test_scheduled_release_ops_weekly_review_returns_disabled_when_flag_off():
    with patch("src.core.tasks.release_ops_tasks.settings.release_ops_enabled", False):
        result = await scheduled_release_ops_weekly_review()

    assert result["status"] == "disabled"
    assert result["task"] == "scheduled_release_ops_weekly_review"


async def test_scheduled_release_ops_weekly_review_runs_cycle_when_enabled(tmp_path: Path):
    weekly_result = {
        "report": {
            "selection": {"selected_trace_key_count": 3},
            "batch_result": {"applied_count": 2, "failed_count": 0},
            "export_summary": {"golden_dialogue_size": 4},
        },
        "report_path": tmp_path / "weekly_cycle.json",
    }
    weekly_result["report_path"].write_text("{}", encoding="utf-8")

    with (
        patch("src.core.tasks.release_ops_tasks.settings.release_ops_enabled", True),
        patch(
            "src.core.tasks.release_ops_tasks.settings.release_ops_reviewer",
            "release-ops",
        ),
        patch(
            "src.core.tasks.release_ops_tasks.settings.release_ops_apply_weekly_review",
            True,
        ),
        patch(
            "src.core.tasks.release_ops_tasks.run_weekly_review_cycle",
            AsyncMock(return_value=weekly_result),
        ) as mock_cycle,
    ):
        result = await scheduled_release_ops_weekly_review()

    assert result["status"] == "ok"
    assert result["selected_trace_key_count"] == 3
    assert result["applied_count"] == 2
    mock_cycle.assert_awaited_once()


async def test_scheduled_release_ops_cycle_runs_when_enabled(tmp_path: Path):
    cycle_result = {
        "report": {
            "overall_status": "hold",
            "exit_code": 2,
        },
        "report_path": tmp_path / "release_cycle.json",
        "summary_paths": {"markdown": tmp_path / "summary.md"},
        "checklist_paths": {"markdown": tmp_path / "checklist.md"},
    }
    cycle_result["report_path"].write_text("{}", encoding="utf-8")
    cycle_result["summary_paths"]["markdown"].write_text("summary", encoding="utf-8")
    cycle_result["checklist_paths"]["markdown"].write_text("checklist", encoding="utf-8")

    with (
        patch("src.core.tasks.release_ops_tasks.settings.release_ops_enabled", True),
        patch(
            "src.core.tasks.release_ops_tasks.run_release_ops_cycle",
            AsyncMock(return_value=cycle_result),
        ) as mock_cycle,
    ):
        result = await scheduled_release_ops_cycle()

    assert result["status"] == "hold"
    assert result["exit_code"] == 2
    assert result["summary_path"].endswith("summary.md")
    mock_cycle.assert_awaited_once()
