"""Brief orchestrator — LangGraph StateGraph for morning_brief + evening_recap.

Replaces the ad-hoc asyncio.gather() in skill handlers with a proper
LangGraph DAG that runs cross-domain collectors in parallel, then
synthesizes the collected data into a single message.

Graph structure::

    collect_calendar ──┐
    collect_tasks ─────┤
    collect_finance ───┼──► synthesize ──► END
    collect_email ─────┤
    collect_outstanding┘

All collector nodes run in parallel (fan-out). The synthesize node runs
after all collectors complete (fan-in).
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

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


def build_brief_graph() -> StateGraph:
    """Build the brief orchestrator graph with parallel collector fan-out."""
    graph = StateGraph(BriefState)

    # Collector nodes (run in parallel via fan-out)
    graph.add_node("collect_calendar", collect_calendar)
    graph.add_node("collect_tasks", collect_tasks)
    graph.add_node("collect_finance", collect_finance)
    graph.add_node("collect_email", collect_email)
    graph.add_node("collect_outstanding", collect_outstanding)

    # Synthesizer node (fan-in: waits for all collectors)
    graph.add_node("synthesize", synthesize)

    # Fan-out: entry point goes to all collectors in parallel
    graph.set_entry_point("collect_calendar")
    graph.add_edge("collect_calendar", "collect_tasks")
    graph.add_edge("collect_tasks", "collect_finance")
    graph.add_edge("collect_finance", "collect_email")
    graph.add_edge("collect_email", "collect_outstanding")

    # Fan-in: all collectors → synthesize → END
    graph.add_edge("collect_outstanding", "synthesize")
    graph.add_edge("synthesize", END)

    return graph


# Compiled graph (singleton)
_brief_graph = build_brief_graph().compile()


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

        try:
            result = await _brief_graph.ainvoke(initial_state)
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
