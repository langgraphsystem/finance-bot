"""State definition for the generic approval graph."""

from typing import Any, TypedDict


class ApprovalState(TypedDict, total=False):
    """State for the approval (pending action) LangGraph orchestrator.

    This graph replaces the Redis-based ``pending_actions.py`` flow with
    a LangGraph interrupt/resume pattern backed by a checkpointer.
    """

    # Set at creation
    intent: str
    user_id: str
    family_id: str
    action_data: dict[str, Any]

    # Set by approval node after interrupt resumes
    approved: bool

    # Set by executor node
    result_text: str
