"""Email orchestrator state definition."""

from typing import TypedDict


class EmailState(TypedDict, total=False):
    """State for the email LangGraph orchestrator."""

    intent: str
    message_text: str
    user_id: str
    language: str

    # Populated by reader node
    emails: list[dict]
    thread_messages: list[dict]
    summary: str

    # Populated by writer node
    draft_to: str
    draft_subject: str
    draft_body: str
    revision_count: int

    # Populated by reviewer node
    quality_ok: bool
    revision_feedback: str

    # Final output
    response_text: str
    sent: bool
