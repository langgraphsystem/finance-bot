"""Brief orchestrator — LangGraph StateGraph for morning_brief + evening_recap.

Graph structure (true parallel fan-out → fan-in)::

    START ──┬── collect_calendar ──┐
            ├── collect_tasks ─────┤
            ├── collect_finance ───┼──► synthesize ──► END
            ├── collect_email ─────┤
            └── collect_outstanding┘

All collector nodes run in parallel (fan-out from START).
The synthesize node runs after all collectors complete (fan-in).
Collector nodes are cached for 60 seconds to avoid redundant queries.
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import CachePolicy

from src.core.config import settings
from src.core.context import SessionContext
from src.core.plugin_loader import plugin_loader
from src.gateway.types import IncomingMessage
from src.orchestrators.brief.nodes import (
    collect_calendar,
    collect_email,
    collect_finance,
    collect_outstanding,
    collect_tasks,
    synthesize,
)
from src.orchestrators.brief.state import BriefState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_COLLECTORS = [
    "collect_calendar",
    "collect_tasks",
    "collect_finance",
    "collect_email",
    "collect_outstanding",
]

_COLLECTOR_FUNCS = {
    "collect_calendar": collect_calendar,
    "collect_tasks": collect_tasks,
    "collect_finance": collect_finance,
    "collect_email": collect_email,
    "collect_outstanding": collect_outstanding,
}

# Cache collector results for 60 seconds — avoids redundant DB/API
# queries when the user triggers multiple briefs in quick succession.
COLLECTOR_CACHE_TTL = 60
_collector_cache_policy = CachePolicy(ttl=COLLECTOR_CACHE_TTL)


def build_brief_graph_parallel() -> StateGraph:
    """Build the brief graph with true parallel fan-out from START."""
    graph = StateGraph(BriefState)

    for name, fn in _COLLECTOR_FUNCS.items():
        graph.add_node(name, fn, cache_policy=_collector_cache_policy)
    graph.add_node("synthesize", synthesize)

    # Fan-out: START → all collectors in parallel
    for name in _COLLECTORS:
        graph.add_edge(START, name)

    # Fan-in: all collectors → synthesize (waits for all)
    for name in _COLLECTORS:
        graph.add_edge(name, "synthesize")

    graph.add_edge("synthesize", END)

    return graph


def build_brief_graph_sequential() -> StateGraph:
    """Build the brief graph with sequential collector chain (legacy)."""
    graph = StateGraph(BriefState)

    for name, fn in _COLLECTOR_FUNCS.items():
        graph.add_node(name, fn, cache_policy=_collector_cache_policy)
    graph.add_node("synthesize", synthesize)

    graph.add_edge(START, "collect_calendar")
    graph.add_edge("collect_calendar", "collect_tasks")
    graph.add_edge("collect_tasks", "collect_finance")
    graph.add_edge("collect_finance", "collect_email")
    graph.add_edge("collect_email", "collect_outstanding")
    graph.add_edge("collect_outstanding", "synthesize")
    graph.add_edge("synthesize", END)

    return graph


def _compile_brief_graph():
    """Compile the brief graph with optional checkpointer."""
    if settings.ff_langgraph_brief_parallel:
        builder = build_brief_graph_parallel()
    else:
        builder = build_brief_graph_sequential()

    if settings.ff_langgraph_checkpointer:
        from src.orchestrators.checkpointer import get_checkpointer

        return builder.compile(checkpointer=get_checkpointer())
    return builder.compile()


# Compiled graph (singleton)
_brief_graph = _compile_brief_graph()


class BriefOrchestrator:
    """Morning brief / evening recap orchestrator.

    Routes morning_brief and evening_recap intents through a LangGraph
    that collects data from all connected domains in parallel, then
    synthesizes a single coherent message.
    """

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Run the brief orchestrator graph."""
        plugin = plugin_loader.load(context.business_type)

        if intent == "evening_recap":
            sections = plugin.evening_recap_sections
        else:
            sections = plugin.morning_brief_sections

        initial_state: BriefState = {
            "intent": intent,
            "user_id": context.user_id,
            "family_id": context.family_id,
            "language": context.language or "en",
            "business_type": context.business_type,
            "active_sections": sections,
            "calendar_data": "",
            "tasks_data": "",
            "finance_data": "",
            "email_data": "",
            "outstanding_data": "",
            "response_text": "",
        }

        config: dict[str, Any] = {}
        if settings.ff_langgraph_checkpointer:
            thread_id = f"brief-{context.user_id}-{intent}"
            config = {"configurable": {"thread_id": thread_id}}

        try:
            result = await _brief_graph.ainvoke(initial_state, config or None)
            text = result.get("response_text", "")
            if text:
                return SkillResult(response_text=text)
            return SkillResult(
                response_text="Couldn't prepare your brief. Try again later."
            )
        except Exception as e:
            logger.exception("Brief orchestrator failed: %s", e)
            return SkillResult(
                response_text="Couldn't prepare your brief. Try again later."
            )
