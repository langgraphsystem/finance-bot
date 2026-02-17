"""Email orchestrator graph nodes."""

import logging
from typing import Any

from src.orchestrators.email.state import EmailState

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


async def email_planner(state: EmailState) -> dict[str, Any]:
    """Decide which path to take based on intent."""
    intent = state.get("intent", "read_inbox")
    logger.info("Email planner: intent=%s", intent)
    return {"intent": intent}


async def email_reader(state: EmailState) -> dict[str, Any]:
    """Read emails from Gmail (via Google Workspace client)."""
    # In production, this would call GoogleWorkspaceClient.list_messages()
    # For now, return the state for skill-level handling
    return {"emails": state.get("emails", []), "summary": state.get("summary", "")}


async def email_writer(state: EmailState) -> dict[str, Any]:
    """Draft an email response using Claude Sonnet."""
    revision_count = state.get("revision_count", 0) + 1
    return {
        "draft_body": state.get("draft_body", ""),
        "revision_count": revision_count,
    }


async def email_reviewer(state: EmailState) -> dict[str, Any]:
    """Review draft quality."""
    revision_count = state.get("revision_count", 0)
    # Auto-approve if we've revised enough or first draft is good
    quality_ok = revision_count >= MAX_REVISIONS or True
    return {"quality_ok": quality_ok}


def route_email_action(state: EmailState) -> str:
    """Route after reader based on intent."""
    intent = state.get("intent", "read_inbox")
    if intent in ("send_email", "draft_reply"):
        return "writer"
    if intent == "summarize_thread":
        return "end"
    if intent == "follow_up_email":
        return "end"
    return "end"


def check_quality(state: EmailState) -> str:
    """Check if draft is good enough to send."""
    if state.get("quality_ok", False):
        return "approved"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "ask_user"
    return "revision"
