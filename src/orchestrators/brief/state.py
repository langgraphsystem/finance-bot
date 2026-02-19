"""Brief orchestrator state definition."""

from typing import TypedDict


class BriefState(TypedDict, total=False):
    """State for the morning_brief / evening_recap LangGraph orchestrator."""

    intent: str
    user_id: str
    family_id: str
    language: str
    business_type: str | None

    # Per-collector raw text (filled by collector nodes)
    calendar_data: str
    tasks_data: str
    finance_data: str
    email_data: str
    outstanding_data: str

    # Sections to include (from plugin config)
    active_sections: list[str]

    # Final synthesized output
    response_text: str
