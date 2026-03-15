"""Collector wrappers for scheduled actions.

Architecture note — dependency inversion:
  SIA depends on its own CollectorContext abstraction, NOT on BriefState.
  Brief orchestrator imports are isolated inside _brief_adapter() and loaded
  lazily so that refactoring Brief never breaks SIA directly — only the
  adapter needs to be updated.

  Dependency graph (desired):
    collectors.py → CollectorContext (own type)
    collectors.py → brief.nodes      (via lazy adapter, single callsite)
    brief.graph   → brief.nodes      (unchanged)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from src.core.models.scheduled_action import ScheduledAction

SourceStatus = dict[str, dict[str, Any]]
SOURCE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class CollectorContext:
    """Minimal context for SIA data collectors.

    Decoupled from BriefState so SIA is not affected by Brief refactors.
    Only carries the three fields all collectors actually need.
    """

    user_id: str
    family_id: str
    language: str


def build_collector_context(action: ScheduledAction) -> CollectorContext:
    """Build a CollectorContext from a ScheduledAction."""
    return CollectorContext(
        user_id=str(action.user_id),
        family_id=str(action.family_id),
        language=action.language or "en",
    )


def _to_brief_state(ctx: CollectorContext) -> Any:
    """Adapter: convert CollectorContext → BriefState.

    All BriefState / brief.state imports are contained here.
    If Brief is refactored, only this function needs to change.
    """
    from src.orchestrators.brief.state import BriefState  # lazy import

    return BriefState(
        intent="morning_brief",
        user_id=ctx.user_id,
        family_id=ctx.family_id,
        language=ctx.language,
        business_type=None,
        active_sections=[],
    )


def _brief_adapter(node_path: str, response_key: str):
    """Return an async collector fn that wraps a brief node.

    Args:
        node_path:    dotted attribute inside brief.nodes, e.g. "collect_calendar"
        response_key: key in the returned dict, e.g. "calendar_data"

    All brief.nodes imports are contained here.
    """

    async def _collect(ctx: CollectorContext) -> tuple[str, str]:
        from src.orchestrators.brief import nodes as brief_nodes  # lazy import

        node_fn = getattr(brief_nodes, node_path)
        state = _to_brief_state(ctx)
        result = await node_fn(state)
        text = str(result.get(response_key, "") or "")
        return text, "success" if text else "empty"

    _collect.__name__ = node_path
    return _collect


# Registry of supported sources.
# Adding a new source = one line here; no other SIA files need to change.
_SOURCE_COLLECTORS: dict[str, Any] = {
    "calendar":       _brief_adapter("collect_calendar",    "calendar_data"),
    "tasks":          _brief_adapter("collect_tasks",       "tasks_data"),
    "money_summary":  _brief_adapter("collect_finance",     "finance_data"),
    "email_highlights": _brief_adapter("collect_email",     "email_data"),
    "outstanding":    _brief_adapter("collect_outstanding", "outstanding_data"),
}


async def _run_source(
    source: str,
    ctx: CollectorContext,
) -> tuple[str, str, dict[str, Any]]:
    collect = _SOURCE_COLLECTORS[source]
    try:
        text, status = await asyncio.wait_for(
            collect(ctx),
            timeout=SOURCE_TIMEOUT_SECONDS,
        )
        return source, text, {"status": status}
    except TimeoutError:
        return source, "", {"status": "failed", "error": "timeout"}
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return source, "", {"status": "failed", "error": str(exc)[:300]}


async def collect_sources(action: ScheduledAction) -> tuple[dict[str, str], SourceStatus]:
    """Collect selected sources in parallel and return payload + source status."""
    selected_sources = [
        source for source in (action.sources or []) if source in _SOURCE_COLLECTORS
    ]
    if not selected_sources:
        selected_sources = ["calendar", "tasks"]

    ctx = build_collector_context(action)

    async def _run_with_duration(source: str) -> tuple[str, str, dict[str, Any]]:
        started = time.perf_counter()
        src, text, meta = await _run_source(source, ctx)
        meta["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return src, text, meta

    results = await asyncio.gather(*[_run_with_duration(source) for source in selected_sources])

    payload: dict[str, str] = {}
    status: SourceStatus = {}
    for source, text, meta in results:
        payload[source] = text
        status[source] = meta

    return payload, status
