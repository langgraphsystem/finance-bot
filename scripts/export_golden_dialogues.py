"""Export reviewed production traces into golden-dialogue regression artifacts.

Usage:
    python scripts/export_golden_dialogues.py
    python scripts/export_golden_dialogues.py --limit 100
    python scripts/export_golden_dialogues.py --base-url https://example.com
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

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "scripts" / "test_results"


def infer_base_url() -> str:
    """Infer the public app base URL from available environment variables."""
    explicit_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if explicit_base_url:
        return explicit_base_url.rstrip("/")

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if webhook_url:
        return webhook_url.rsplit("/", 1)[0].rstrip("/")

    return "http://localhost:8000"


def build_headers(health_secret: str) -> dict[str, str]:
    """Build auth headers for ops endpoints."""
    if not health_secret:
        return {}
    return {"Authorization": f"Bearer {health_secret}"}


def dialogues_to_jsonl(dialogues: list[dict[str, Any]]) -> str:
    """Convert golden dialogues to newline-delimited JSON for eval pipelines."""
    return "\n".join(
        json.dumps(dialogue, ensure_ascii=False, sort_keys=True)
        for dialogue in dialogues
    )


async def fetch_ops_exports(
    *,
    base_url: str,
    limit: int,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Fetch analytics exports from operator endpoints."""
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        golden_task = client.get(
            urljoin(f"{base_url}/", "ops/analytics/golden-dialogues"),
            params={"limit": limit},
        )
        curation_task = client.get(
            urljoin(f"{base_url}/", "ops/analytics/weekly-curation"),
            params={"limit": limit},
        )
        golden_resp, curation_resp = await asyncio.gather(golden_task, curation_task)
        golden_resp.raise_for_status()
        curation_resp.raise_for_status()

    golden_payload = golden_resp.json()
    curation_payload = curation_resp.json()
    return {
        "exported_at": datetime.now().isoformat(),
        "base_url": base_url,
        "limit": limit,
        "golden_dialogues": golden_payload.get("golden_dialogues", []),
        "golden_dialogue_size": golden_payload.get("golden_dialogue_size", 0),
        "weekly_curation": curation_payload,
    }


def save_export_bundle(bundle: dict[str, Any], *, out_dir: Path, prefix: str) -> dict[str, Path]:
    """Persist JSON + JSONL export artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    summary_path = out_dir / f"{prefix}_{timestamp}.json"
    snapshot_path = out_dir / f"{prefix}_weekly_{timestamp}.json"
    jsonl_path = out_dir / f"{prefix}_{timestamp}.jsonl"

    summary_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    snapshot_path.write_text(
        json.dumps(bundle["weekly_curation"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    jsonl_path.write_text(
        dialogues_to_jsonl(bundle["golden_dialogues"]),
        encoding="utf-8",
    )
    return {
        "summary": summary_path,
        "weekly_snapshot": snapshot_path,
        "jsonl": jsonl_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export reviewed production traces as golden-dialogue artifacts."
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
        help="Number of reviewed traces to export (default: 50)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(RESULTS_DIR),
        help="Directory for export artifacts (default: scripts/test_results)",
    )
    parser.add_argument(
        "--prefix",
        default="golden_dialogues",
        help="Artifact filename prefix",
    )
    args = parser.parse_args()

    bundle = asyncio.run(
        fetch_ops_exports(
            base_url=args.base_url.rstrip("/"),
            limit=max(1, min(args.limit, 500)),
            headers=build_headers(args.health_secret),
        )
    )
    paths = save_export_bundle(
        bundle,
        out_dir=Path(args.out_dir),
        prefix=args.prefix,
    )

    print(f"Exported {bundle['golden_dialogue_size']} golden dialogues")
    print(f"Summary: {paths['summary']}")
    print(f"Weekly snapshot: {paths['weekly_snapshot']}")
    print(f"JSONL: {paths['jsonl']}")


if __name__ == "__main__":
    main()
