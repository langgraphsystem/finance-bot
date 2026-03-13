"""Run the weekly review cycle for analytics, review queue, and golden exports.

Usage:
    python scripts/run_weekly_review_cycle.py --reviewer qa-1
    python scripts/run_weekly_review_cycle.py --reviewer qa-1 --apply
    python scripts/run_weekly_review_cycle.py --reviewer qa-1 --apply --max-selected 25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from scripts.export_golden_dialogues import (
    RESULTS_DIR,
    build_headers,
    fetch_ops_exports,
    infer_base_url,
    save_export_bundle,
)


def build_batch_payload(
    *,
    reviewer: str,
    notes: str,
    labels: list[str],
    selection_limit: int,
    max_selected: int,
    review_label: str | None,
    suggested_action: str | None,
    suggested_final_label: str | None,
    tag: str | None,
    source: str | None,
) -> dict[str, Any]:
    """Build the selector-based batch review payload."""
    return {
        "trace_keys": [],
        "reviewer": reviewer,
        "notes": notes,
        "labels": labels,
        "selection_limit": max(1, min(selection_limit, 100)),
        "max_selected": max(1, min(max_selected, 100)),
        "review_label": review_label,
        "suggested_action": suggested_action,
        "suggested_final_label": suggested_final_label,
        "tag": tag,
        "source": source,
    }


async def fetch_review_selection(
    *,
    base_url: str,
    headers: dict[str, str],
    limit: int,
    max_selected: int,
    review_label: str | None,
    suggested_action: str | None,
    suggested_final_label: str | None,
    tag: str | None,
    source: str | None,
) -> dict[str, Any]:
    """Fetch the filtered review queue snapshot used for the weekly cycle."""
    params = {
        "limit": max(1, min(limit, 100)),
        "max_selected": max(1, min(max_selected, 100)),
    }
    if review_label:
        params["review_label"] = review_label
    if suggested_action:
        params["suggested_action"] = suggested_action
    if suggested_final_label:
        params["suggested_final_label"] = suggested_final_label
    if tag:
        params["tag"] = tag
    if source:
        params["source"] = source

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        response = await client.get(
            urljoin(f"{base_url}/", "ops/analytics/review-queue"),
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def apply_batch_review(
    *,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply selector-based review suggestions through the ops endpoint."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        response = await client.post(
            urljoin(f"{base_url}/", "ops/analytics/reviews/apply-suggestions-batch"),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def save_cycle_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> Path:
    """Persist the weekly review cycle report as JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = out_dir / f"{prefix}_{timestamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


async def run_weekly_review_cycle(
    *,
    base_url: str,
    headers: dict[str, str],
    reviewer: str,
    apply: bool,
    limit: int,
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
    out_dir: Path,
    export_prefix: str,
    report_prefix: str,
) -> dict[str, Any]:
    """Run the weekly review workflow and persist export artifacts."""
    selection = await fetch_review_selection(
        base_url=base_url,
        headers=headers,
        limit=limit,
        max_selected=max_selected,
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
    )

    batch_payload = build_batch_payload(
        reviewer=reviewer,
        notes=notes,
        labels=labels,
        selection_limit=selection_limit,
        max_selected=max_selected,
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
    )
    batch_result = None
    if apply and selection.get("selected_trace_key_count", 0):
        batch_result = await apply_batch_review(
            base_url=base_url,
            headers=headers,
            payload=batch_payload,
        )

    export_bundle = await fetch_ops_exports(
        base_url=base_url,
        limit=max(1, min(export_limit, 500)),
        headers=headers,
    )
    export_paths = save_export_bundle(
        export_bundle,
        out_dir=out_dir,
        prefix=export_prefix,
    )

    cycle_report = {
        "executed_at": datetime.now().isoformat(),
        "base_url": base_url,
        "reviewer": reviewer,
        "apply": apply,
        "selection_filters": {
            "review_label": review_label,
            "suggested_action": suggested_action,
            "suggested_final_label": suggested_final_label,
            "tag": tag,
            "source": source,
        },
        "selection": selection,
        "batch_payload": batch_payload,
        "batch_result": batch_result,
        "export_summary": {
            "golden_dialogue_size": export_bundle["golden_dialogue_size"],
            "review_result_size": export_bundle["weekly_curation"].get(
                "review_result_size",
                0,
            ),
            "dataset_candidate_size": export_bundle["weekly_curation"].get(
                "dataset_candidate_size",
                0,
            ),
            "review_batch_size": export_bundle["weekly_curation"].get("review_batch_size", 0),
            "feedback_size": export_bundle["weekly_curation"].get("feedback_size", 0),
        },
        "export_paths": {name: str(path) for name, path in export_paths.items()},
    }
    report_path = save_cycle_report(
        cycle_report,
        out_dir=out_dir,
        prefix=report_prefix,
    )
    return {
        "report": cycle_report,
        "report_path": report_path,
        "export_paths": export_paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the weekly review cycle for analytics and golden dialogue exports."
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
        required=True,
        help="Reviewer name for batch review actions",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply batch review suggestions instead of dry-run selection only",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Review queue snapshot limit (default: 50)",
    )
    parser.add_argument(
        "--selection-limit",
        type=int,
        default=100,
        help="Max queue items considered for selector-based batch apply (default: 100)",
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
        help="Golden dialogue export limit after the cycle (default: 100)",
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
        help="Directory for weekly review artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--export-prefix",
        default="weekly_golden_dialogues",
        help="Filename prefix for exported golden dialogue artifacts",
    )
    parser.add_argument(
        "--report-prefix",
        default="weekly_review_cycle",
        help="Filename prefix for the weekly cycle report",
    )
    args = parser.parse_args()

    headers = build_headers(args.health_secret)
    result = asyncio.run(
        run_weekly_review_cycle(
            base_url=args.base_url.rstrip("/"),
            headers=headers,
            reviewer=args.reviewer.strip(),
            apply=args.apply,
            limit=args.limit,
            selection_limit=args.selection_limit,
            max_selected=args.max_selected,
            export_limit=args.export_limit,
            notes=args.notes,
            labels=args.labels,
            review_label=args.review_label,
            suggested_action=args.suggested_action,
            suggested_final_label=args.suggested_final_label,
            tag=args.tag,
            source=args.source,
            out_dir=Path(args.out_dir),
            export_prefix=args.export_prefix,
            report_prefix=args.report_prefix,
        )
    )

    report = result["report"]
    print(
        "Selection:",
        report["selection"].get("selected_trace_key_count", 0),
        "candidates",
    )
    if report["batch_result"]:
        print(
            "Applied:",
            report["batch_result"]["applied_count"],
            "Failed:",
            report["batch_result"]["failed_count"],
        )
    else:
        print("Applied: dry-run")
    print("Report:", result["report_path"])
    print("Golden dialogues:", result["export_paths"]["jsonl"])


if __name__ == "__main__":
    main()
