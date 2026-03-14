"""Run the weekly review cycle and release checklist as one operator workflow.

Usage:
    python scripts/run_release_ops_cycle.py --reviewer qa-1
    python scripts/run_release_ops_cycle.py --reviewer qa-1 --apply-weekly-review
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_golden_dialogues import RESULTS_DIR, build_headers, infer_base_url  # noqa: E402
from scripts.generate_release_checklist import (  # noqa: E402
    DEFAULT_QUALITY_THRESHOLDS,
    build_release_checklist,
    fetch_release_inputs,
    save_release_checklist,
)
from scripts.run_weekly_review_cycle import run_weekly_review_cycle  # noqa: E402


def get_exit_code(overall_status: str) -> int:
    """Map release readiness status to a CI-friendly process exit code."""
    return {
        "ready": 0,
        "hold": 2,
        "rollback": 3,
    }.get(overall_status, 1)


def save_release_ops_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> Path:
    """Persist the combined release ops cycle report as JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = out_dir / f"{prefix}_{timestamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def build_release_summary(cycle_report: dict[str, Any]) -> dict[str, Any]:
    """Build a concise operator summary from the full release ops cycle report."""
    checklist_report = dict(cycle_report["checklist"]["report"])
    checklist_inputs = dict(checklist_report["inputs"])
    decision = dict(checklist_inputs["release_decision"])
    release_health = dict(checklist_inputs["health_detailed"].get("release_health") or {})
    quality_metrics = dict(checklist_inputs.get("quality_metrics") or {})
    quality_rates = dict(quality_metrics.get("rates") or {})

    blocking_checks = [
        check["detail"]
        for check in checklist_report["checks"]
        if check["blocking"] and check["status"] == "fail"
    ]
    warning_checks = [
        check["detail"]
        for check in checklist_report["checks"]
        if check["status"] == "warn"
    ]

    return {
        "executed_at": cycle_report["executed_at"],
        "base_url": cycle_report["base_url"],
        "overall_status": cycle_report["overall_status"],
        "exit_code": cycle_report["exit_code"],
        "rollout": {
            "current_percent": decision.get("current_rollout_percent", 0),
            "target_percent": decision.get("target_rollout_percent", 0),
            "next_action": decision.get("next_action", "unknown"),
            "release_health_status": release_health.get("status", "unknown"),
            "release_health_action": release_health.get("recommended_action", "ignore"),
        },
        "quality": {
            "status": quality_metrics.get("status", "unknown"),
            "review_count": quality_metrics.get("review_count", 0),
            "task_completion_rate": quality_rates.get("task_completion_rate", 0.0),
            "response_useful_rate": quality_rates.get("response_useful_rate", 0.0),
            "wrong_route_rate": quality_rates.get("wrong_route_rate", 0.0),
            "memory_failure_rate": quality_rates.get("memory_failure_rate", 0.0),
            "tool_failure_rate": quality_rates.get("tool_failure_rate", 0.0),
            "user_dissatisfaction_signal_rate": quality_rates.get(
                "user_dissatisfaction_signal_rate",
                0.0,
            ),
        },
        "weekly_cycle": {
            "selection_count": cycle_report["weekly_cycle"]["selection_count"],
            "applied_count": (
                cycle_report["weekly_cycle"]["batch_result"]["applied_count"]
                if cycle_report["weekly_cycle"]["batch_result"]
                else 0
            ),
            "failed_count": (
                cycle_report["weekly_cycle"]["batch_result"]["failed_count"]
                if cycle_report["weekly_cycle"]["batch_result"]
                else 0
            ),
            "golden_dialogue_size": cycle_report["weekly_cycle"]["export_summary"].get(
                "golden_dialogue_size",
                0,
            ),
        },
        "blocking_issues": blocking_checks[:5],
        "warnings": warning_checks[:5],
    }


def render_release_summary_markdown(summary: dict[str, Any]) -> str:
    """Render a concise release summary for operator handoff and release review."""
    rollout = summary["rollout"]
    quality = summary["quality"]
    weekly_cycle = summary["weekly_cycle"]
    lines = [
        "# Release Summary",
        "",
        f"- Executed at: {summary['executed_at']}",
        f"- Base URL: {summary['base_url']}",
        f"- Overall status: {summary['overall_status'].upper()}",
        f"- Exit code: {summary['exit_code']}",
        "",
        "## Rollout",
        (
            "- Current -> target: "
            f"{rollout['current_percent']}% -> {rollout['target_percent']}%"
        ),
        f"- Next action: {rollout['next_action']}",
        (
            "- Release health: "
            f"{rollout['release_health_status']} ({rollout['release_health_action']})"
        ),
        "",
        "## Quality",
        f"- Quality status: {quality['status']}",
        f"- Reviewed traces: {quality['review_count']}",
        f"- Task completion: {float(quality['task_completion_rate']):.2%}",
        f"- Response useful: {float(quality['response_useful_rate']):.2%}",
        f"- Wrong-route rate: {float(quality['wrong_route_rate']):.2%}",
        f"- Memory-failure rate: {float(quality['memory_failure_rate']):.2%}",
        f"- Tool-failure rate: {float(quality['tool_failure_rate']):.2%}",
        (
            "- User dissatisfaction rate: "
            f"{float(quality['user_dissatisfaction_signal_rate']):.2%}"
        ),
        "",
        "## Weekly Cycle",
        f"- Selected traces: {weekly_cycle['selection_count']}",
        f"- Applied reviews: {weekly_cycle['applied_count']}",
        f"- Failed reviews: {weekly_cycle['failed_count']}",
        f"- Golden dialogues exported: {weekly_cycle['golden_dialogue_size']}",
    ]
    if summary["blocking_issues"]:
        lines.extend(["", "## Blocking Issues"])
        lines.extend(f"- {item}" for item in summary["blocking_issues"])
    if summary["warnings"]:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in summary["warnings"])
    return "\n".join(lines) + "\n"


def save_release_summary(
    summary: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> dict[str, Path]:
    """Persist the concise release summary as JSON and Markdown artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = out_dir / f"{prefix}_{timestamp}.json"
    markdown_path = out_dir / f"{prefix}_{timestamp}.md"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_release_summary_markdown(summary),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": markdown_path}


async def run_release_ops_cycle(
    *,
    base_url: str,
    headers: dict[str, str],
    reviewer: str,
    apply_weekly_review: bool,
    review_limit: int,
    selection_limit: int,
    max_selected: int,
    export_limit: int,
    notes: str,
    labels: list[str],
    review_label: str | None,
    suggested_action: str | None,
    suggested_final_label: str | None,
    tag: str | None,
    source: str | None,
    max_review_backlog: int,
    quality_thresholds: dict[str, float],
    out_dir: Path,
    export_prefix: str,
    weekly_report_prefix: str,
    checklist_prefix: str,
    summary_prefix: str,
    cycle_prefix: str,
) -> dict[str, Any]:
    """Execute weekly curation and release readiness evaluation as one workflow."""
    weekly_result = await run_weekly_review_cycle(
        base_url=base_url,
        headers=headers,
        reviewer=reviewer,
        apply=apply_weekly_review,
        limit=review_limit,
        selection_limit=selection_limit,
        max_selected=max_selected,
        export_limit=export_limit,
        notes=notes,
        labels=labels,
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
        out_dir=out_dir,
        export_prefix=export_prefix,
        report_prefix=weekly_report_prefix,
    )

    checklist_inputs = await fetch_release_inputs(
        base_url=base_url,
        headers=headers,
        limit=review_limit,
    )
    checklist_report = build_release_checklist(
        checklist_inputs,
        max_review_backlog=max_review_backlog,
        quality_thresholds=quality_thresholds,
    )
    checklist_paths = save_release_checklist(
        checklist_report,
        out_dir=out_dir,
        prefix=checklist_prefix,
    )

    overall_status = checklist_report["overall_status"]
    cycle_report = {
        "executed_at": datetime.now().isoformat(),
        "base_url": base_url,
        "reviewer": reviewer,
        "apply_weekly_review": apply_weekly_review,
        "overall_status": overall_status,
        "exit_code": get_exit_code(overall_status),
        "weekly_cycle": {
            "selection_count": weekly_result["report"]["selection"].get(
                "selected_trace_key_count",
                0,
            ),
            "batch_result": weekly_result["report"]["batch_result"],
            "export_summary": weekly_result["report"]["export_summary"],
            "report_path": str(weekly_result["report_path"]),
            "export_paths": {
                name: str(path)
                for name, path in weekly_result["export_paths"].items()
            },
        },
        "checklist": {
            "report": checklist_report,
            "paths": {
                name: str(path)
                for name, path in checklist_paths.items()
            },
        },
    }
    release_summary = build_release_summary(cycle_report)
    summary_paths = save_release_summary(
        release_summary,
        out_dir=out_dir,
        prefix=summary_prefix,
    )
    cycle_report["summary"] = release_summary
    cycle_report["summary_paths"] = {name: str(path) for name, path in summary_paths.items()}
    cycle_report_path = save_release_ops_report(
        cycle_report,
        out_dir=out_dir,
        prefix=cycle_prefix,
    )
    return {
        "report": cycle_report,
        "report_path": cycle_report_path,
        "checklist_paths": checklist_paths,
        "summary_paths": summary_paths,
        "weekly_result": weekly_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run weekly review curation and release readiness checks as one workflow."
    )
    parser.add_argument(
        "--base-url",
        default=infer_base_url(),
        help="Base URL for ops endpoints (default: inferred from env)",
    )
    parser.add_argument(
        "--health-secret",
        default=os.getenv("HEALTH_SECRET", ""),
        help="Bearer token for protected ops endpoints",
    )
    parser.add_argument(
        "--reviewer",
        default="release-ops",
        help="Reviewer name used for weekly review actions (default: release-ops)",
    )
    parser.add_argument(
        "--apply-weekly-review",
        action="store_true",
        help="Apply selector-based weekly review suggestions before checklist generation",
    )
    parser.add_argument(
        "--review-limit",
        type=int,
        default=50,
        help="Review queue snapshot limit (default: 50)",
    )
    parser.add_argument(
        "--selection-limit",
        type=int,
        default=100,
        help="Max queue items considered for selector-based apply (default: 100)",
    )
    parser.add_argument(
        "--max-selected",
        type=int,
        default=25,
        help="Max selected traces to apply in one batch (default: 25)",
    )
    parser.add_argument(
        "--export-limit",
        type=int,
        default=100,
        help="Golden dialogue export limit after weekly cycle (default: 100)",
    )
    parser.add_argument(
        "--max-review-backlog",
        type=int,
        default=25,
        help="Warn when review backlog exceeds this threshold (default: 25)",
    )
    parser.add_argument(
        "--notes",
        default="weekly review cycle",
        help="Notes stored with batch review actions",
    )
    parser.add_argument(
        "--max-wrong-route-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["max_wrong_route_rate"],
        help="Fail when wrong-route rate exceeds this threshold (default: 0.20)",
    )
    parser.add_argument(
        "--max-memory-failure-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["max_memory_failure_rate"],
        help="Fail when memory-failure rate exceeds this threshold (default: 0.15)",
    )
    parser.add_argument(
        "--max-tool-failure-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["max_tool_failure_rate"],
        help="Fail when tool-failure rate exceeds this threshold (default: 0.15)",
    )
    parser.add_argument(
        "--max-user-dissatisfaction-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["max_user_dissatisfaction_rate"],
        help="Fail when unhelpful feedback share exceeds this threshold (default: 0.40)",
    )
    parser.add_argument(
        "--min-task-completion-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["min_task_completion_rate"],
        help="Fail when task completion rate drops below this floor (default: 0.70)",
    )
    parser.add_argument(
        "--min-response-useful-rate",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLDS["min_response_useful_rate"],
        help="Fail when response usefulness rate drops below this floor (default: 0.70)",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="Additional labels for batch review actions (repeatable)",
    )
    parser.add_argument(
        "--review-label",
        default=None,
        help="Review queue filter: review_label",
    )
    parser.add_argument(
        "--suggested-action",
        default="promote_to_dataset",
        help="Review queue filter: suggested_action (default: promote_to_dataset)",
    )
    parser.add_argument(
        "--suggested-final-label",
        default=None,
        help="Review queue filter: suggested_final_label",
    )
    parser.add_argument(
        "--tag",
        default="golden_replay",
        help="Review queue filter: tag (default: golden_replay)",
    )
    parser.add_argument(
        "--source",
        default="test_bot_live_golden_replay",
        help="Review queue filter: source (default: test_bot_live_golden_replay)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for release ops artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--export-prefix",
        default="weekly_golden_dialogues",
        help="Filename prefix for golden dialogue exports",
    )
    parser.add_argument(
        "--weekly-report-prefix",
        default="weekly_review_cycle",
        help="Filename prefix for weekly review reports",
    )
    parser.add_argument(
        "--checklist-prefix",
        default="release_checklist",
        help="Filename prefix for release checklist artifacts",
    )
    parser.add_argument(
        "--summary-prefix",
        default="release_summary",
        help="Filename prefix for concise release summary artifacts",
    )
    parser.add_argument(
        "--cycle-prefix",
        default="release_ops_cycle",
        help="Filename prefix for the combined release ops report",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_release_ops_cycle(
            base_url=args.base_url.rstrip("/"),
            headers=build_headers(args.health_secret),
            reviewer=args.reviewer.strip(),
            apply_weekly_review=args.apply_weekly_review,
            review_limit=max(1, min(args.review_limit, 100)),
            selection_limit=max(1, min(args.selection_limit, 100)),
            max_selected=max(1, min(args.max_selected, 100)),
            export_limit=max(1, min(args.export_limit, 500)),
            notes=args.notes,
            labels=args.labels,
            review_label=args.review_label,
            suggested_action=args.suggested_action,
            suggested_final_label=args.suggested_final_label,
            tag=args.tag,
            source=args.source,
            max_review_backlog=max(0, args.max_review_backlog),
            quality_thresholds={
                "max_wrong_route_rate": max(0.0, args.max_wrong_route_rate),
                "max_memory_failure_rate": max(0.0, args.max_memory_failure_rate),
                "max_tool_failure_rate": max(0.0, args.max_tool_failure_rate),
                "max_user_dissatisfaction_rate": max(
                    0.0,
                    args.max_user_dissatisfaction_rate,
                ),
                "min_task_completion_rate": max(0.0, args.min_task_completion_rate),
                "min_response_useful_rate": max(0.0, args.min_response_useful_rate),
            },
            out_dir=Path(args.out_dir),
            export_prefix=args.export_prefix,
            weekly_report_prefix=args.weekly_report_prefix,
            checklist_prefix=args.checklist_prefix,
            summary_prefix=args.summary_prefix,
            cycle_prefix=args.cycle_prefix,
        )
    )

    report = result["report"]
    print(f"Overall status: {report['overall_status'].upper()}")
    print(f"Exit code: {report['exit_code']}")
    print(f"Cycle report: {result['report_path']}")
    print(f"Checklist JSON: {result['checklist_paths']['json']}")
    print(f"Checklist Markdown: {result['checklist_paths']['markdown']}")
    print(f"Summary JSON: {result['summary_paths']['json']}")
    print(f"Summary Markdown: {result['summary_paths']['markdown']}")
    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
