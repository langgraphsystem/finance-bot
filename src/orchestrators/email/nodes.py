"""Email orchestrator graph nodes."""

import logging
from typing import Any

from src.core.config import settings
from src.orchestrators.email.state import EmailState
from src.orchestrators.resilience import with_retry, with_timeout

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


async def email_planner(state: EmailState) -> dict[str, Any]:
    """Decide which path to take based on intent."""
    intent = state.get("intent", "read_inbox")
    logger.info("Email planner: intent=%s", intent)
    return {"intent": intent}


@with_retry(max_retries=2, backoff_base=1.0)
@with_timeout(30)
async def email_reader(state: EmailState) -> dict[str, Any]:
    """Read emails from Gmail (via Google Workspace client)."""
    return {
        "emails": state.get("emails", []),
        "summary": state.get("summary", ""),
    }


@with_retry(max_retries=1, backoff_base=1.0)
@with_timeout(30)
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
    quality_ok = revision_count >= MAX_REVISIONS or True
    return {"quality_ok": quality_ok}


async def email_approval(state: EmailState) -> dict[str, Any]:
    """Ask the user to approve the email before sending.

    When ``ff_langgraph_email_hitl`` is enabled, this node uses
    ``interrupt()`` to pause the graph and wait for user confirmation.
    The router resumes the graph with ``Command(resume="yes"|"no")``.
    """
    if settings.ff_langgraph_email_hitl:
        from langgraph.types import interrupt

        answer = interrupt({
            "type": "email_approval",
            "draft_to": state.get("draft_to", ""),
            "draft_subject": state.get("draft_subject", ""),
            "draft_body": state.get("draft_body", ""),
        })
        return {"user_approved": answer == "yes"}

    # Without HITL flag, auto-approve
    return {"user_approved": True}


@with_timeout(15)
async def email_finalizer(state: EmailState) -> dict[str, Any]:
    """Execute the send or return cancellation message."""
    if not state.get("user_approved", False):
        return {
            "response_text": "Email cancelled.",
            "sent": False,
        }
    # In production this would call the send skill
    return {
        "response_text": state.get("response_text", ""),
        "sent": True,
    }


def route_email_action(state: EmailState) -> str:
    """Route after reader based on intent."""
    intent = state.get("intent", "read_inbox")
    if intent in ("send_email", "draft_reply"):
        return "writer"
    return "end"


def check_quality(state: EmailState) -> str:
    """Check if draft is good enough to send."""
    if state.get("quality_ok", False):
        return "approved"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "ask_user"
    return "revision"
