"""Validate and optionally start the first controlled canary rollout.

Usage:
    python scripts/start_controlled_canary.py
    python scripts/start_controlled_canary.py --apply --actor qa-1
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
from urllib.parse import urljoin

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_golden_dialogues import (  # noqa: E402
    RESULTS_DIR,
    build_headers,
    infer_base_url,
)


async def fetch_canary_inputs(
    *,
    base_url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Fetch the current release overview, decision, and quality metrics."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        overview_task = client.get(urljoin(f"{base_url}/", "ops/release/overview"))
        decision_task = client.get(urljoin(f"{base_url}/", "ops/release/decision"))
        quality_task = client.get(
            urljoin(f"{base_url}/", "ops/analytics/quality-metrics"),
            params={"limit": 100},
        )
        overview_resp, decision_resp, quality_resp = await asyncio.gather(
            overview_task,
            decision_task,
            quality_task,
        )
        overview_resp.raise_for_status()
        decision_resp.raise_for_status()
        quality_resp.raise_for_status()

    return {
        "fetched_at": datetime.now().isoformat(),
        "base_url": base_url,
        "overview": overview_resp.json(),
        "decision": decision_resp.json(),
        "quality_metrics": quality_resp.json(),
    }


def build_canary_payload(
    inputs: dict[str, Any],
    *,
    actor: str,
    target_rollout_percent: int,
    shadow_mode: bool,
    notes: str,
) -> dict[str, Any]:
    """Build a safe first-canary override payload after validating cohort readiness."""
    overview = dict(inputs["overview"])
    decision = dict(inputs["decision"])
    switches = dict(overview.get("switches") or {})
    configured = dict(switches.get("configured_cohorts") or {})
    trusted_cohorts = (
        int(configured.get("internal") or 0)
        + int(configured.get("trusted") or 0)
        + int(configured.get("beta") or 0)
    )
    if trusted_cohorts <= 0:
        raise ValueError("trusted_cohorts_not_configured")

    if str(decision.get("next_action") or "") == "rollback":
        raise ValueError("release_decision_recommends_rollback")

    current_rollout_percent = int(decision.get("current_rollout_percent") or 0)
    target_percent = max(1, min(target_rollout_percent, 100))
    action = "progress" if target_percent > current_rollout_percent else "set"

    return {
        "actor": actor.strip() or "release-ops",
        "action": action,
        "rollout_percent": target_percent,
        "shadow_mode": bool(shadow_mode),
        "notes": notes.strip() or "start first controlled canary",
    }


async def apply_canary_override(
    *,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply the canary override through the release ops endpoint."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        response = await client.post(
            urljoin(f"{base_url}/", "ops/release/overrides"),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def render_canary_report_markdown(report: dict[str, Any]) -> str:
    """Render a concise canary bootstrap report."""
    decision = report["inputs"]["decision"]
    quality = report["inputs"]["quality_metrics"]
    quality_rates = dict(quality.get("rates") or {})
    lines = [
        "# Controlled Canary Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Base URL: {report['base_url']}",
        f"- Applied: {'yes' if report['applied'] else 'no'}",
        f"- Current rollout: {decision.get('current_rollout_percent', 0)}%",
        f"- Decision before apply: {decision.get('next_action', 'unknown')}",
        f"- Quality status: {quality.get('status', 'unknown')}",
        (
            "- Wrong-route rate: "
            f"{float(quality_rates.get('wrong_route_rate') or 0.0):.2%}"
        ),
        (
            "- Task completion rate: "
            f"{float(quality_rates.get('task_completion_rate') or 0.0):.2%}"
        ),
    ]
    if report["applied_result"]:
        lines.extend(
            [
                "",
                "## Applied Override",
                f"- Action: {report['applied_result']['override'].get('action', 'unknown')}",
                (
                    "- Rollout percent: "
                    f"{report['applied_result']['override'].get('rollout_percent', 0)}%"
                ),
                (
                    "- Shadow mode: "
                    f"{'on' if report['applied_result']['override'].get('shadow_mode') else 'off'}"
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def save_canary_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> dict[str, Path]:
    """Persist canary bootstrap artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = out_dir / f"{prefix}_{timestamp}.json"
    markdown_path = out_dir / f"{prefix}_{timestamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_canary_report_markdown(report),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": markdown_path}


async def start_controlled_canary(
    *,
    base_url: str,
    headers: dict[str, str],
    actor: str,
    apply: bool,
    target_rollout_percent: int,
    shadow_mode: bool,
    notes: str,
    out_dir: Path,
    prefix: str,
) -> dict[str, Any]:
    """Validate canary readiness and optionally apply the first rollout override."""
    inputs = await fetch_canary_inputs(base_url=base_url, headers=headers)
    payload = build_canary_payload(
        inputs,
        actor=actor,
        target_rollout_percent=target_rollout_percent,
        shadow_mode=shadow_mode,
        notes=notes,
    )
    applied_result = None
    if apply:
        applied_result = await apply_canary_override(
            base_url=base_url,
            headers=headers,
            payload=payload,
        )

    report = {
        "generated_at": datetime.now().isoformat(),
        "base_url": base_url,
        "applied": apply,
        "payload": payload,
        "applied_result": applied_result,
        "inputs": inputs,
    }
    paths = save_canary_report(report, out_dir=out_dir, prefix=prefix)
    return {
        "report": report,
        "paths": paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and optionally start the first controlled canary rollout."
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
        "--actor",
        default="release-ops",
        help="Actor recorded for the override action (default: release-ops)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the canary override instead of generating a dry-run report",
    )
    parser.add_argument(
        "--target-rollout-percent",
        type=int,
        default=1,
        help="Target rollout percent for the first canary stage (default: 1)",
    )
    parser.add_argument(
        "--shadow-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep shadow mode enabled for the canary bootstrap",
    )
    parser.add_argument(
        "--notes",
        default="start first controlled canary",
        help="Operator notes stored with the override action",
    )
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for canary bootstrap artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--prefix",
        default="controlled_canary",
        help="Artifact filename prefix",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(
            start_controlled_canary(
                base_url=args.base_url.rstrip("/"),
                headers=build_headers(args.health_secret),
                actor=args.actor,
                apply=args.apply,
                target_rollout_percent=args.target_rollout_percent,
                shadow_mode=args.shadow_mode,
                notes=args.notes,
                out_dir=Path(args.out_dir),
                prefix=args.prefix,
            )
        )
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Controlled canary bootstrap failed: {exc}")
        raise SystemExit(1) from exc
    report = result["report"]
    print(f"Applied: {'yes' if report['applied'] else 'no'}")
    print(f"JSON: {result['paths']['json']}")
    print(f"Markdown: {result['paths']['markdown']}")


if __name__ == "__main__":
    main()
