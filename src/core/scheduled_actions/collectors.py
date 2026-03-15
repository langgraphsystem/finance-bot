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
    Only carries the three fields all collectors actually need,
    plus optional per-source extras (e.g. news_topic for the news collector).
    """

    user_id: str
    family_id: str
    language: str
    # Optional extras for specialised collectors
    news_topic: str = ""
    event_condition: str = ""  # for event_check: the condition to monitor


def build_collector_context(action: ScheduledAction) -> CollectorContext:
    """Build a CollectorContext from a ScheduledAction."""
    schedule_cfg: dict = action.schedule_config or {}
    return CollectorContext(
        user_id=str(action.user_id),
        family_id=str(action.family_id),
        language=action.language or "en",
        news_topic=schedule_cfg.get("news_topic", "") or "",
        event_condition=schedule_cfg.get("event_condition", "") or "",
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


def _news_adapter():
    """Return an async collector fn that fetches news via dual_search.

    The topic is read from ctx.news_topic — populated by build_collector_context()
    from action.schedule_config["news_topic"].
    All research imports are lazy to preserve the DI boundary.
    """

    async def _collect_news(ctx: CollectorContext) -> tuple[str, str]:
        from src.core.config import settings  # lazy import
        from src.core.research.dual_search import dual_search  # lazy import

        topic = ctx.news_topic
        if not topic:
            return "", "empty"

        # Map language codes → full names for the prompt instruction
        _LANG_NAMES: dict[str, str] = {
            "en": "English", "ru": "Russian", "es": "Spanish",
            "de": "German",  "fr": "French",  "it": "Italian",
            "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese",
            "ar": "Arabic",  "tr": "Turkish", "pl": "Polish",
        }

        # Reuse the same Gemini-backed searcher as web_search skill
        async def _gemini_search(query: str, language: str) -> str:
            from google.genai import types  # lazy import

            from src.core.llm.clients import google_client  # lazy import

            lang_name = _LANG_NAMES.get(language, "English")
            localized_prompt = (
                f"Find the latest news and updates about: {query}\n\n"
                f"Requirements:\n"
                f"- Respond ONLY in {lang_name}\n"
                f"- Use Telegram HTML formatting (<b>, <i>) — no Markdown\n"
                f"- Group results as bullet points with source name in <i>italics</i>\n"
                f"- Max 8 items, prioritise recency (last 48 hours)\n"
                f"- Skip paywalled or unavailable articles"
            )

            client = google_client()
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=localized_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            return response.text or ""

        use_dual = bool(
            getattr(settings, "ff_dual_search", False)
            and getattr(settings, "xai_api_key", None)
        )
        try:
            if use_dual:
                text = await dual_search(
                    topic,
                    ctx.language,
                    topic,
                    gemini_searcher=_gemini_search,
                    trace_user_id=ctx.user_id,
                )
            else:
                text = await _gemini_search(topic, ctx.language)
            return text, "success" if text else "empty"
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("News collector failed for topic=%r: %s", topic, exc)
            return "", "failed"

    _collect_news.__name__ = "collect_news"
    return _collect_news


def _event_check_adapter():
    """Return an async collector that checks whether a custom event has occurred.

    Uses Gemini Google Search to search for the condition from ctx.event_condition.
    Returns non-empty text (description of event) when detected → triggers completion.
    Returns empty string when event has NOT yet occurred.
    """

    async def _collect_event(ctx: CollectorContext) -> tuple[str, str]:
        condition = ctx.event_condition
        if not condition:
            return "", "empty"

        _LANG_NAMES: dict[str, str] = {
            "en": "English", "ru": "Russian", "es": "Spanish",
            "de": "German",  "fr": "French",  "it": "Italian",
            "pt": "Portuguese", "zh": "Chinese", "ja": "Japanese",
            "ar": "Arabic",  "tr": "Turkish", "pl": "Polish",
        }
        lang_name = _LANG_NAMES.get(ctx.language, "English")

        prompt = (
            f"Search the web to determine whether the following event has already occurred:\n"
            f'"{condition}"\n\n'
            f"Rules:\n"
            f"- If the event HAS occurred: respond in {lang_name} with a brief 2-3 sentence "
            f"summary — what happened, when, and a source name. Use Telegram HTML (<b>, <i>).\n"
            f"- If the event has NOT occurred yet: respond with exactly the word: NOT_YET\n"
            f"- Do not add any other text when responding NOT_YET."
        )

        try:
            from google.genai import types  # lazy import

            from src.core.llm.clients import google_client  # lazy import

            client = google_client()
            response = await client.aio.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = (response.text or "").strip()

            # If Gemini says NOT_YET (or empty) → event not yet detected
            if not text or "NOT_YET" in text:
                return "", "not_triggered"

            return text, "triggered"

        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Event check failed for condition=%r: %s", condition, exc
            )
            return "", "failed"

    _collect_event.__name__ = "collect_event_check"
    return _collect_event


# Registry of supported sources.
# Adding a new source = one line here; no other SIA files need to change.
_SOURCE_COLLECTORS: dict[str, Any] = {
    "calendar":         _brief_adapter("collect_calendar",    "calendar_data"),
    "tasks":            _brief_adapter("collect_tasks",       "tasks_data"),
    "money_summary":    _brief_adapter("collect_finance",     "finance_data"),
    "email_highlights": _brief_adapter("collect_email",       "email_data"),
    "outstanding":      _brief_adapter("collect_outstanding", "outstanding_data"),
    "news":             _news_adapter(),
    "event_check":      _event_check_adapter(),
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
