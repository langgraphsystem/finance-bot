"""Email orchestrator — LangGraph StateGraph.

Nodes: planner → reader → writer → reviewer → approval → finalizer
Handles: read_inbox, send_email, draft_reply, follow_up_email, summarize_thread

The approval node uses LangGraph ``interrupt()`` for human-in-the-loop
confirmation before sending, replacing the old Redis pending-action flow.
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.core.config import settings
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.email.nodes import (
    check_quality,
    email_approval,
    email_finalizer,
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
    """Build the email orchestrator graph with optional HITL approval."""
    graph = StateGraph(EmailState)

    graph.add_node("planner", email_planner)
    graph.add_node("reader", email_reader)
    graph.add_node("writer", email_writer)
    graph.add_node("reviewer", email_reviewer)
    graph.add_node("approval", email_approval)
    graph.add_node("finalizer", email_finalizer)

    graph.add_edge(START, "planner")
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
            "approved": "approval",
            "revision": "writer",
            "ask_user": "approval",
        },
    )
    graph.add_edge("approval", "finalizer")
    graph.add_edge("finalizer", END)

    return graph


def _compile_email_graph():
    """Compile the email graph with optional checkpointer."""
    builder = build_email_graph()
    if settings.ff_langgraph_checkpointer:
        from src.orchestrators.checkpointer import get_checkpointer

        return builder.compile(checkpointer=get_checkpointer())
    return builder.compile()


# Lazy-compiled graph (singleton)
_email_graph = None


def _get_email_graph():
    """Lazy-init the email graph on first use."""
    global _email_graph
    if _email_graph is None:
        _email_graph = _compile_email_graph()
    return _email_graph


class EmailOrchestrator:
    """Email domain orchestrator — routes through LangGraph for complex flows.

    Simple intents (read_inbox, summarize_thread, follow_up_email) delegate
    directly to skills via AgentRouter. Compose intents (send_email,
    draft_reply) go through the LangGraph revision loop.
    """

    _GRAPH_INTENTS = {"send_email", "draft_reply"}

    def __init__(self, agent_router: Any = None):
        self._agent_router = agent_router

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route email intents through graph or directly to skills."""
        if intent in self._GRAPH_INTENTS:
            try:
                initial_state: EmailState = {
                    "intent": intent,
                    "message_text": message.text or "",
                    "user_id": context.user_id,
                    "language": context.language or "en",
                    "emails": [],
                    "thread_messages": [],
                    "summary": "",
                    "draft_to": "",
                    "draft_subject": "",
                    "draft_body": "",
                    "revision_count": 0,
                    "quality_ok": False,
                    "revision_feedback": "",
                    "user_approved": False,
                    "response_text": "",
                    "sent": False,
                }

                config: dict[str, Any] = {}
                if settings.ff_langgraph_checkpointer:
                    thread_id = (
                        f"email-{context.user_id}-{intent}-"
                        f"{message.id}"
                    )
                    config = {
                        "configurable": {"thread_id": thread_id}
                    }

                result = await _get_email_graph().ainvoke(
                    initial_state, config or None
                )

                # If the graph was interrupted (HITL), return the draft
                # preview with confirmation buttons
                interrupts = result.get("__interrupt__", [])
                if interrupts:
                    return self._build_approval_result(
                        interrupts[0], config
                    )

                text = result.get("response_text", "")
                if text:
                    return SkillResult(response_text=text)
            except Exception as e:
                logger.warning(
                    "Email graph failed for %s, falling back: %s",
                    intent,
                    e,
                )

        if self._agent_router:
            return await self._agent_router.route(
                intent, message, context, intent_data
            )
        return SkillResult(
            response_text="Email feature is being set up."
        )

    @staticmethod
    def _build_approval_result(
        intr: Any,
        config: dict[str, Any],
    ) -> SkillResult:
        """Build a SkillResult with approval buttons from an interrupt."""
        data = intr.value if hasattr(intr, "value") else intr
        thread_id = config.get("configurable", {}).get(
            "thread_id", ""
        )

        to = data.get("draft_to", "")
        subj = data.get("draft_subject", "")
        body = data.get("draft_body", "")

        preview = f"<b>To:</b> {to}\n<b>Subject:</b> {subj}\n\n{body}"
        buttons = [
            {
                "text": "📨 Send",
                "callback": f"graph_resume:{thread_id}:yes",
            },
            {
                "text": "❌ Cancel",
                "callback": f"graph_resume:{thread_id}:no",
            },
        ]
        return SkillResult(response_text=preview, buttons=buttons)

    async def resume(
        self, thread_id: str, answer: str
    ) -> SkillResult:
        """Resume a paused email graph after user approval/rejection."""
        from langgraph.types import Command

        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = await _get_email_graph().ainvoke(
                Command(resume=answer), config
            )
            text = result.get("response_text", "")
            return SkillResult(response_text=text or "Done.")
        except Exception as e:
            logger.error("Email graph resume failed: %s", e)
            return SkillResult(
                response_text="Failed to process your response."
            )
