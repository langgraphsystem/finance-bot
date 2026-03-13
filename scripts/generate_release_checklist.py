"""Generate a release readiness checklist from rollout and analytics endpoints.

Usage:
    python scripts/generate_release_checklist.py
    python scripts/generate_release_checklist.py --base-url https://example.com
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

from scripts.export_golden_dialogues import RESULTS_DIR, build_headers, infer_base_url


def _check(status: str, name: str, detail: str, *, blocking: bool) -> dict[str, Any]:
    return {
        "status": status,
        "name": name,
        "detail": detail,
        "blocking": blocking,
    }


async def fetch_release_inputs(
    *,
    base_url: str,
    headers: dict[str, str],
    limit: int,
) -> dict[str, Any]:
    """Fetch the operator snapshots required for a release checklist."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        health_task = client.get(urljoin(f"{base_url}/", "health/detailed"))
        overview_task = client.get(urljoin(f"{base_url}/", "ops/release/overview"))
        decision_task = client.get(urljoin(f"{base_url}/", "ops/release/decision"))
        overrides_task = client.get(
            urljoin(f"{base_url}/", "ops/release/overrides"),
            params={"limit": limit},
        )
        weekly_task = client.get(
            urljoin(f"{base_url}/", "ops/analytics/weekly-curation"),
            params={"limit": limit},
        )
        review_queue_task = client.get(
            urljoin(f"{base_url}/", "ops/analytics/review-queue"),
            params={"limit": limit, "max_selected": min(limit, 100)},
        )
        responses = await asyncio.gather(
            health_task,
            overview_task,
            decision_task,
            overrides_task,
            weekly_task,
            review_queue_task,
        )
        for response in responses:
            response.raise_for_status()

    return {
        "generated_at": datetime.now().isoformat(),
        "base_url": base_url,
        "health_detailed": responses[0].json(),
        "release_overview": responses[1].json(),
        "release_decision": responses[2].json(),
        "release_overrides": responses[3].json(),
        "weekly_curation": responses[4].json(),
        "review_queue": responses[5].json(),
    }


def build_release_checklist(
    inputs: dict[str, Any],
    *,
    max_review_backlog: int = 25,
) -> dict[str, Any]:
    """Build a release checklist with pass/warn/fail checks."""
    health_detailed = dict(inputs["health_detailed"])
    release_decision = dict(inputs["release_decision"])
    release_overrides = dict(inputs["release_overrides"])
    weekly_curation = dict(inputs["weekly_curation"])
    review_queue = dict(inputs["review_queue"])

    checks: list[dict[str, Any]] = []

    core_status = str(health_detailed.get("status") or "unknown")
    if core_status == "ok":
        checks.append(
            _check(
                "pass",
                "core_services",
                "API, Redis and database are healthy.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "fail",
                "core_services",
                f"Core health status is {core_status}.",
                blocking=True,
            )
        )

    release_health = dict(health_detailed.get("release_health") or {})
    release_health_status = str(release_health.get("status") or "unknown")
    recommended_action = str(release_health.get("recommended_action") or "ignore")
    if release_health_status == "healthy":
        checks.append(
            _check(
                "pass",
                "release_health",
                "Release health gates are healthy.",
                blocking=True,
            )
        )
    elif release_health_status == "degraded":
        checks.append(
            _check(
                "warn",
                "release_health",
                "Release health is degraded; expansion should be held.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "fail",
                "release_health",
                f"Release health status is {release_health_status} ({recommended_action}).",
                blocking=True,
            )
        )

    next_action = str(release_decision.get("next_action") or "unknown")
    target_rollout_percent = release_decision.get("target_rollout_percent", 0)
    if next_action == "rollback":
        checks.append(
            _check(
                "fail",
                "rollout_decision",
                f"Decision recommends rollback to {target_rollout_percent}%.",
                blocking=True,
            )
        )
    elif next_action == "hold":
        checks.append(
            _check(
                "warn",
                "rollout_decision",
                f"Decision recommends hold at {target_rollout_percent}%.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "rollout_decision",
                f"Decision allows progression to {target_rollout_percent}%.",
                blocking=True,
            )
        )

    active_override = dict(release_overrides.get("active_override") or {})
    if active_override:
        checks.append(
            _check(
                "warn",
                "override_state",
                "An active release override is in effect.",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "override_state",
                "No active release override.",
                blocking=False,
            )
        )

    backlog_size = int(review_queue.get("review_queue_size") or 0)
    if backlog_size > max_review_backlog:
        checks.append(
            _check(
                "warn",
                "review_backlog",
                f"Review backlog size {backlog_size} exceeds threshold {max_review_backlog}.",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "review_backlog",
                f"Review backlog size {backlog_size} is within threshold {max_review_backlog}.",
                blocking=False,
            )
        )

    feedback_counts = dict(weekly_curation.get("feedback_counts") or {})
    helpful = int(feedback_counts.get("helpful") or 0)
    unhelpful = int(feedback_counts.get("unhelpful") or 0)
    if unhelpful > helpful:
        checks.append(
            _check(
                "warn",
                "user_feedback",
                f"Unhelpful feedback ({unhelpful}) exceeds helpful feedback ({helpful}).",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "user_feedback",
                f"Helpful feedback ({helpful}) is not below unhelpful feedback ({unhelpful}).",
                blocking=False,
            )
        )

    dataset_candidate_size = int(weekly_curation.get("dataset_candidate_size") or 0)
    if dataset_candidate_size <= 0:
        checks.append(
            _check(
                "warn",
                "dataset_freshness",
                "No dataset candidates found in the weekly snapshot.",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "dataset_freshness",
                f"Weekly snapshot contains {dataset_candidate_size} dataset candidates.",
                blocking=False,
            )
        )

    statuses = {check["status"] for check in checks if check["blocking"]}
    if "fail" in statuses or next_action == "rollback":
        overall_status = "rollback"
    elif "warn" in statuses or next_action == "hold":
        overall_status = "hold"
    elif any(check["status"] == "warn" for check in checks):
        overall_status = "hold"
    else:
        overall_status = "ready"

    return {
        "generated_at": inputs["generated_at"],
        "base_url": inputs["base_url"],
        "overall_status": overall_status,
        "checks": checks,
        "inputs": inputs,
    }


def render_release_checklist_markdown(report: dict[str, Any]) -> str:
    """Render the release checklist into a concise Markdown summary."""
    lines = [
        "# Release Checklist",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Base URL: {report['base_url']}",
        f"- Overall status: {report['overall_status'].upper()}",
        "",
        "## Checks",
    ]
    for check in report["checks"]:
        marker = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]"}[check["status"]]
        lines.append(f"- {marker} {check['name']}: {check['detail']}")

    inputs = report["inputs"]
    weekly = inputs["weekly_curation"]
    decision = inputs["release_decision"]
    overrides = inputs["release_overrides"]
    lines.extend(
        [
            "",
            "## Rollout",
            f"- Current rollout: {decision.get('current_rollout_percent', 0)}%",
            f"- Target rollout: {decision.get('target_rollout_percent', 0)}%",
            f"- Next action: {decision.get('next_action', 'unknown')}",
            f"- Active override: {'yes' if overrides.get('active_override') else 'no'}",
            "",
            "## Weekly Analytics",
            f"- Review results: {weekly.get('review_result_size', 0)}",
            f"- Dataset candidates: {weekly.get('dataset_candidate_size', 0)}",
            f"- Review batches: {weekly.get('review_batch_size', 0)}",
            f"- Feedback items: {weekly.get('feedback_size', 0)}",
        ]
    )
    return "\n".join(lines) + "\n"


def save_release_checklist(
    report: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> dict[str, Path]:
    """Persist JSON and Markdown release checklist artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = out_dir / f"{prefix}_{timestamp}.json"
    markdown_path = out_dir / f"{prefix}_{timestamp}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_release_checklist_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a release readiness checklist from rollout and analytics endpoints."
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
        "--limit",
        type=int,
        default=50,
        help="Snapshot limit for checklist inputs (default: 50)",
    )
    parser.add_argument(
        "--max-review-backlog",
        type=int,
        default=25,
        help="Warn when review backlog exceeds this threshold (default: 25)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for release checklist artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--prefix",
        default="release_checklist",
        help="Artifact filename prefix",
    )
    args = parser.parse_args()

    inputs = asyncio.run(
        fetch_release_inputs(
            base_url=args.base_url.rstrip("/"),
            headers=build_headers(args.health_secret),
            limit=max(1, min(args.limit, 100)),
        )
    )
    report = build_release_checklist(
        inputs,
        max_review_backlog=max(0, args.max_review_backlog),
    )
    paths = save_release_checklist(
        report,
        out_dir=Path(args.out_dir),
        prefix=args.prefix,
    )

    print(f"Overall status: {report['overall_status'].upper()}")
    print(f"JSON: {paths['json']}")
    print(f"Markdown: {paths['markdown']}")


if __name__ == "__main__":
    main()
