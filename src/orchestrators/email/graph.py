"""Email orchestrator — LangGraph StateGraph.

Nodes: planner → reader → writer → reviewer → finalizer
Handles: read_inbox, send_email, draft_reply, follow_up_email, summarize_thread

For P0, skills handle execution directly. The orchestrator provides the
multi-step framework for P1 revision loops.
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.email.nodes import (
    check_quality,
    email_planner,
    email_reader,
    email_reviewer,
    email_writer,
    route_email_action,
)
from src.orchestrators.email.state import EmailState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def build_email_graph() -> StateGraph:
    """Build the email orchestrator graph."""
    graph = StateGraph(EmailState)

    graph.add_node("planner", email_planner)
    graph.add_node("reader", email_reader)
    graph.add_node("writer", email_writer)
    graph.add_node("reviewer", email_reviewer)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "reader")
    graph.add_conditional_edges(
        "reader",
        route_email_action,
        {
            "writer": "writer",
            "end": END,
        },
    )
    graph.add_edge("writer", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        check_quality,
        {
            "approved": END,
            "revision": "writer",
            "ask_user": END,
        },
    )

    return graph


# Compiled graph (singleton)
_email_graph = build_email_graph().compile()


class EmailOrchestrator:
    """Email domain orchestrator — routes through LangGraph for complex flows.

    For P0, delegates to skills directly via AgentRouter for simple operations.
    The LangGraph handles the revision loop for compose/reply flows.
    """

    def __init__(self, agent_router: Any = None):
        self._agent_router = agent_router

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route email intents — P0 delegates to AgentRouter."""
        # For P0, delegate directly to skills via AgentRouter
        # P1 will use _email_graph for compose/reply revision loops
        if self._agent_router:
            return await self._agent_router.route(intent, message, context, intent_data)

        # Fallback: return a generic response
        return SkillResult(response_text="Email feature is being set up.")
