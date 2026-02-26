"""Approval orchestrator — LangGraph interrupt/resume for destructive actions.

Replaces the Redis-based ``pending_actions.py`` flow with a durable
LangGraph graph that pauses at the approval node and resumes when the
user clicks a confirmation button.

Graph structure::

    START → ask_approval → execute_action → END

The ``ask_approval`` node calls ``interrupt()`` which pauses the graph.
When the user confirms/cancels, the router calls ``resume()`` with
``Command(resume="yes"|"no")``.
"""

import logging
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.orchestrators.approval.nodes import ask_approval, execute_action
from src.orchestrators.approval.state import ApprovalState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def build_approval_graph() -> StateGraph:
    """Build the approval graph."""
    graph = StateGraph(ApprovalState)
    graph.add_node("ask_approval", ask_approval)
    graph.add_node("execute_action", execute_action)
    graph.add_edge(START, "ask_approval")
    graph.add_edge("ask_approval", "execute_action")
    graph.add_edge("execute_action", END)
    return graph


_approval_graph = None


def _get_approval_graph():
    """Lazily compile with checkpointer."""
    global _approval_graph
    if _approval_graph is not None:
        return _approval_graph

    from src.core.config import settings
    from src.orchestrators.checkpointer import get_checkpointer

    checkpointer = get_checkpointer() if settings.ff_langgraph_checkpointer else None
    _approval_graph = build_approval_graph().compile(checkpointer=checkpointer)
    return _approval_graph


async def start_approval(
    intent: str,
    user_id: str,
    family_id: str,
    action_data: dict[str, Any],
    preview_text: str,
    buttons: list[dict[str, str]] | None = None,
) -> SkillResult:
    """Start an approval flow — invokes the graph which will interrupt.

    Returns a ``SkillResult`` with the preview text and confirmation
    buttons that embed the graph thread_id for resume.
    """
    thread_id = f"approval-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: ApprovalState = {
        "intent": intent,
        "user_id": user_id,
        "family_id": family_id,
        "action_data": action_data,
        "approved": False,
        "result_text": "",
    }

    # This will pause at ask_approval due to interrupt()
    await _get_approval_graph().ainvoke(initial_state, config)

    if buttons is None:
        buttons = [
            {"text": "✅ Confirm", "callback": f"graph_resume:{thread_id}:yes"},
            {"text": "❌ Cancel", "callback": f"graph_resume:{thread_id}:no"},
        ]

    return SkillResult(response_text=preview_text, buttons=buttons)


async def resume_approval(thread_id: str, answer: str) -> str:
    """Resume an interrupted approval graph.

    Args:
        thread_id: The graph thread ID embedded in the callback button.
        answer: ``"yes"`` to confirm, ``"no"`` to cancel.

    Returns:
        The result text from the executor node.
    """
    from langgraph.types import Command

    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await _get_approval_graph().ainvoke(Command(resume=answer), config)
        return result.get("result_text", "Done.")
    except Exception as e:
        logger.error("Approval graph resume failed: %s", e)
        return "Error processing your response. Please try again."
