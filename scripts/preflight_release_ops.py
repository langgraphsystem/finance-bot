"""Validate release-ops environment and ops endpoint readiness.

Usage:
    python scripts/preflight_release_ops.py
    python scripts/preflight_release_ops.py --check-endpoint
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

from scripts.export_golden_dialogues import RESULTS_DIR, build_headers, infer_base_url  # noqa: E402

REQUIRED_KEYS = [
    "APP_ENV",
    "HEALTH_SECRET",
    "RELEASE_ROLLOUT_NAME",
    "RELEASE_OPS_ENABLED",
    "RELEASE_OPS_BASE_URL",
]
COHORT_KEYS = [
    "RELEASE_INTERNAL_USER_IDS",
    "RELEASE_TRUSTED_USER_IDS",
    "RELEASE_BETA_USER_IDS",
]


def _check(status: str, name: str, detail: str) -> dict[str, str]:
    return {
        "status": status,
        "name": name,
        "detail": detail,
    }


def collect_env_snapshot(env: dict[str, str] | None = None) -> dict[str, str]:
    """Collect only release-ops relevant environment variables."""
    source = env or os.environ
    keys = REQUIRED_KEYS + COHORT_KEYS + ["RELEASE_SHADOW_MODE"]
    return {key: str(source.get(key, "")).strip() for key in keys}


async def fetch_endpoint_snapshot(
    *,
    base_url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Fetch minimal ops endpoints required for canary bootstrap."""
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        health_task = client.get(urljoin(f"{base_url}/", "health/detailed"))
        overview_task = client.get(urljoin(f"{base_url}/", "ops/release/overview"))
        decision_task = client.get(urljoin(f"{base_url}/", "ops/release/decision"))
        responses = await asyncio.gather(health_task, overview_task, decision_task)
        for response in responses:
            response.raise_for_status()
    return {
        "health_detailed": responses[0].json(),
        "release_overview": responses[1].json(),
        "release_decision": responses[2].json(),
    }


def build_preflight_report(
    *,
    env_snapshot: dict[str, str],
    base_url: str,
    endpoint_snapshot: dict[str, Any] | None = None,
    endpoint_error: str | None = None,
) -> dict[str, Any]:
    """Build a concise release-ops readiness report."""
    checks: list[dict[str, str]] = []

    missing_keys = [key for key in REQUIRED_KEYS if not env_snapshot.get(key)]
    if missing_keys:
        checks.append(
            _check(
                "fail",
                "required_env",
                f"Missing required env vars: {', '.join(missing_keys)}",
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "required_env",
                "Required release-ops env vars are present.",
            )
        )

    cohort_count = sum(1 for key in COHORT_KEYS if env_snapshot.get(key))
    if cohort_count <= 0:
        checks.append(
            _check(
                "fail",
                "cohorts",
                "No internal/trusted/beta cohort IDs configured.",
            )
        )
    else:
        checks.append(
            _check(
                "pass",
                "cohorts",
                f"Configured cohort groups: {cohort_count}.",
            )
        )

    if env_snapshot.get("RELEASE_OPS_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
        checks.append(
            _check(
                "pass",
                "release_ops_enabled",
                "Scheduled release ops are enabled.",
            )
        )
    else:
        checks.append(
            _check(
                "warn",
                "release_ops_enabled",
                "Scheduled release ops are disabled.",
            )
        )

    if endpoint_snapshot:
        decision = dict(endpoint_snapshot["release_decision"])
        checks.append(
            _check(
                "pass",
                "ops_endpoint",
                (
                    "Ops endpoint reachable; "
                    f"current decision={decision.get('next_action', 'unknown')}."
                ),
            )
        )
    elif endpoint_error:
        checks.append(
            _check(
                "fail",
                "ops_endpoint",
                endpoint_error,
            )
        )
    else:
        checks.append(
            _check(
                "warn",
                "ops_endpoint",
                "Endpoint check skipped.",
            )
        )

    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        overall_status = "not_ready"
    elif "warn" in statuses:
        overall_status = "partial"
    else:
        overall_status = "ready"

    return {
        "generated_at": datetime.now().isoformat(),
        "base_url": base_url,
        "overall_status": overall_status,
        "env_snapshot": env_snapshot,
        "checks": checks,
        "endpoint_snapshot": endpoint_snapshot,
        "endpoint_error": endpoint_error,
    }


def render_preflight_markdown(report: dict[str, Any]) -> str:
    """Render the release-ops preflight report as Markdown."""
    lines = [
        "# Release Ops Preflight",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Base URL: {report['base_url']}",
        f"- Overall status: {report['overall_status'].upper()}",
        "",
        "## Checks",
    ]
    for check in report["checks"]:
        lines.append(f"- [{check['status'].upper()}] {check['name']}: {check['detail']}")
    return "\n".join(lines) + "\n"


def save_preflight_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    prefix: str,
) -> dict[str, Path]:
    """Persist preflight artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    json_path = out_dir / f"{prefix}_{timestamp}.json"
    markdown_path = out_dir / f"{prefix}_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_preflight_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


async def run_preflight(
    *,
    base_url: str,
    headers: dict[str, str],
    check_endpoint: bool,
    out_dir: Path,
    prefix: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run release-ops preflight and persist the result."""
    env_snapshot = collect_env_snapshot(env)
    endpoint_snapshot = None
    endpoint_error = None
    if check_endpoint:
        try:
            endpoint_snapshot = await fetch_endpoint_snapshot(
                base_url=base_url,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            endpoint_error = str(exc)

    report = build_preflight_report(
        env_snapshot=env_snapshot,
        base_url=base_url,
        endpoint_snapshot=endpoint_snapshot,
        endpoint_error=endpoint_error,
    )
    paths = save_preflight_report(report, out_dir=out_dir, prefix=prefix)
    return {
        "report": report,
        "paths": paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate release-ops env and ops endpoint readiness."
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
        "--check-endpoint",
        action="store_true",
        help="Also verify health/release ops endpoints are reachable",
    )
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for preflight artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--prefix",
        default="release_ops_preflight",
        help="Artifact filename prefix",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_preflight(
            base_url=args.base_url.rstrip("/"),
            headers=build_headers(args.health_secret),
            check_endpoint=args.check_endpoint,
            out_dir=Path(args.out_dir),
            prefix=args.prefix,
        )
    )
    report = result["report"]
    print(f"Overall status: {report['overall_status'].upper()}")
    print(f"JSON: {result['paths']['json']}")
    print(f"Markdown: {result['paths']['markdown']}")


if __name__ == "__main__":
    main()
