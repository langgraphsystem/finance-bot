"""Collector wrappers for scheduled actions.

This module reuses brief orchestrator collectors directly to avoid regressions.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.core.models.scheduled_action import ScheduledAction
from src.orchestrators.brief.nodes import (
    collect_calendar,
    collect_email,
    collect_finance,
    collect_outstanding,
    collect_tasks,
)
from src.orchestrators.brief.state import BriefState

SourceStatus = dict[str, dict[str, Any]]
SOURCE_TIMEOUT_SECONDS = 15.0

_SOURCE_COLLECTOR_MAP = {
    "calendar": (collect_calendar, "calendar_data"),
    "tasks": (collect_tasks, "tasks_data"),
    "money_summary": (collect_finance, "finance_data"),
    "email_highlights": (collect_email, "email_data"),
    "outstanding": (collect_outstanding, "outstanding_data"),
}


def build_brief_state(action: ScheduledAction) -> BriefState:
    """Build a minimal BriefState for collector compatibility."""
    return BriefState(
        intent="morning_brief",
        user_id=str(action.user_id),
        family_id=str(action.family_id),
        language=action.language or "en",
        business_type=None,
        active_sections=[],
    )


async def _run_source(
    source: str,
    state: BriefState,
) -> tuple[str, str, dict[str, Any]]:
    collector, response_key = _SOURCE_COLLECTOR_MAP[source]
    try:
        result = await asyncio.wait_for(
            collector(state),
            timeout=SOURCE_TIMEOUT_SECONDS,
        )
        text = str(result.get(response_key, "") or "")
        status = "success" if text else "empty"
        meta: dict[str, Any] = {"status": status}
        return source, text, meta
    except TimeoutError:
        return source, "", {"status": "failed", "error": "timeout"}
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return source, "", {"status": "failed", "error": str(exc)[:300]}


async def collect_sources(action: ScheduledAction) -> tuple[dict[str, str], SourceStatus]:
    """Collect selected sources in parallel and return payload + source status."""
    selected_sources = [
        source for source in (action.sources or []) if source in _SOURCE_COLLECTOR_MAP
    ]
    if not selected_sources:
        selected_sources = ["calendar", "tasks"]

    state = build_brief_state(action)

    async def _run_with_duration(source: str) -> tuple[str, str, dict[str, Any]]:
        started = time.perf_counter()
        src, text, meta = await _run_source(source, state)
        meta["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return src, text, meta

    results = await asyncio.gather(*[_run_with_duration(source) for source in selected_sources])

    payload: dict[str, str] = {}
    status: SourceStatus = {}
    for source, text, meta in results:
        payload[source] = text
        status[source] = meta

    return payload, status
