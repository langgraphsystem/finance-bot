"""Program orchestrator state definition."""

from typing import Any, TypedDict


class ProgramState(TypedDict, total=False):
    """State for the generate_program deep-agent LangGraph orchestrator."""

    intent: str
    user_id: str
    family_id: str
    language: str

    # Input
    message_text: str

    # Extracted by planner node
    requirements: str       # structured requirements (planner output)
    program_language: str   # "python", "javascript", etc.

    # Generated code
    code: str
    filename: str

    # Execution result from E2B
    exec_result: dict[str, Any] | None
    sandbox_url: str | None

    # Review result
    quality_issues: list[str]
    revision_count: int

    # Final
    response_text: str
