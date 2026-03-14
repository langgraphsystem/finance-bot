"""Scheduled release-ops automation tasks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from scripts.export_golden_dialogues import RESULTS_DIR, build_headers, infer_base_url
from scripts.generate_release_checklist import DEFAULT_QUALITY_THRESHOLDS
from scripts.run_release_ops_cycle import run_release_ops_cycle
from scripts.run_weekly_review_cycle import run_weekly_review_cycle
from src.core.config import settings
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


def _resolve_release_ops_base_url() -> str:
    explicit = settings.release_ops_base_url.strip()
    if explicit:
        return explicit.rstrip("/")
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return infer_base_url().rstrip("/")


def _release_ops_headers() -> dict[str, str]:
    return build_headers(settings.health_secret)


def _quality_thresholds() -> dict[str, float]:
    return dict(DEFAULT_QUALITY_THRESHOLDS)


@broker.task(schedule=[{"cron": settings.release_ops_weekly_review_cron}])
async def scheduled_release_ops_weekly_review() -> dict[str, Any]:
    """Run the weekly review cycle on a schedule for release-ops curation."""
    if not settings.release_ops_enabled:
        return {"status": "disabled", "task": "scheduled_release_ops_weekly_review"}

    result = await run_weekly_review_cycle(
        base_url=_resolve_release_ops_base_url(),
        headers=_release_ops_headers(),
        reviewer=settings.release_ops_reviewer,
        apply=settings.release_ops_apply_weekly_review,
        limit=50,
        selection_limit=100,
        max_selected=25,
        export_limit=100,
        notes="scheduled weekly review cycle",
        labels=["weekly_review", "scheduled"],
        review_label=None,
        suggested_action="promote_to_dataset",
        suggested_final_label=None,
        tag="golden_replay",
        source="test_bot_live_golden_replay",
        out_dir=Path(RESULTS_DIR),
        export_prefix="scheduled_weekly_golden_dialogues",
        report_prefix="scheduled_weekly_review_cycle",
    )
    report = result["report"]
    logger.info(
        "Scheduled weekly review completed: selected=%s applied=%s",
        report["selection"].get("selected_trace_key_count", 0),
        report["batch_result"]["applied_count"] if report["batch_result"] else 0,
    )
    return {
        "status": "ok",
        "task": "scheduled_release_ops_weekly_review",
        "report_path": str(result["report_path"]),
        "selected_trace_key_count": report["selection"].get("selected_trace_key_count", 0),
        "applied_count": (
            report["batch_result"]["applied_count"]
            if report["batch_result"]
            else 0
        ),
        "golden_dialogue_size": report["export_summary"].get("golden_dialogue_size", 0),
    }


@broker.task(schedule=[{"cron": settings.release_ops_cycle_cron}])
async def scheduled_release_ops_cycle() -> dict[str, Any]:
    """Run the full release ops cycle on a schedule and persist summary artifacts."""
    if not settings.release_ops_enabled:
        return {"status": "disabled", "task": "scheduled_release_ops_cycle"}

    result = await run_release_ops_cycle(
        base_url=_resolve_release_ops_base_url(),
        headers=_release_ops_headers(),
        reviewer=settings.release_ops_reviewer,
        apply_weekly_review=False,
        review_limit=50,
        selection_limit=100,
        max_selected=25,
        export_limit=100,
        notes="scheduled release ops cycle",
        labels=["scheduled"],
        review_label=None,
        suggested_action="promote_to_dataset",
        suggested_final_label=None,
        tag="golden_replay",
        source="test_bot_live_golden_replay",
        max_review_backlog=25,
        quality_thresholds=_quality_thresholds(),
        out_dir=Path(RESULTS_DIR),
        export_prefix="scheduled_weekly_golden_dialogues",
        weekly_report_prefix="scheduled_weekly_review_cycle",
        checklist_prefix="scheduled_release_checklist",
        summary_prefix="scheduled_release_summary",
        cycle_prefix="scheduled_release_ops_cycle",
    )
    report = result["report"]
    logger.info(
        "Scheduled release ops cycle completed: status=%s exit_code=%s",
        report["overall_status"],
        report["exit_code"],
    )
    return {
        "status": report["overall_status"],
        "task": "scheduled_release_ops_cycle",
        "exit_code": report["exit_code"],
        "report_path": str(result["report_path"]),
        "summary_path": str(result["summary_paths"]["markdown"]),
        "checklist_path": str(result["checklist_paths"]["markdown"]),
    }
