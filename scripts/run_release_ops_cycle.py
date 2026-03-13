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

from scripts.export_golden_dialogues import RESULTS_DIR, build_headers, infer_base_url
from scripts.generate_release_checklist import (
    build_release_checklist,
    fetch_release_inputs,
    save_release_checklist,
)
from scripts.run_weekly_review_cycle import run_weekly_review_cycle


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
    out_dir: Path,
    export_prefix: str,
    weekly_report_prefix: str,
    checklist_prefix: str,
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
    cycle_report_path = save_release_ops_report(
        cycle_report,
        out_dir=out_dir,
        prefix=cycle_prefix,
    )
    return {
        "report": cycle_report,
        "report_path": cycle_report_path,
        "checklist_paths": checklist_paths,
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
            out_dir=Path(args.out_dir),
            export_prefix=args.export_prefix,
            weekly_report_prefix=args.weekly_report_prefix,
            checklist_prefix=args.checklist_prefix,
            cycle_prefix=args.cycle_prefix,
        )
    )

    report = result["report"]
    print(f"Overall status: {report['overall_status'].upper()}")
    print(f"Exit code: {report['exit_code']}")
    print(f"Cycle report: {result['report_path']}")
    print(f"Checklist JSON: {result['checklist_paths']['json']}")
    print(f"Checklist Markdown: {result['checklist_paths']['markdown']}")
    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
