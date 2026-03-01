"""Deep Agent orchestrator state definition.

Holds the evolving state for multi-step task execution:
planning, iterative code generation / data collection, and final assembly.
"""

from typing import Any, TypedDict


class PlanStep(TypedDict):
    """A single step in the deep agent's plan."""

    step: str  # Human-readable description
    status: str  # "pending" | "in_progress" | "done" | "failed"
    output: str  # Result of executing this step


class DeepAgentState(TypedDict, total=False):
    # Identity
    user_id: str
    family_id: str
    language: str

    # Task
    task_description: str
    skill_type: str  # "generate_program" | "tax_report"

    # Planning
    plan: list[PlanStep]
    current_step_index: int

    # Execution context — virtual filesystem
    files: dict[str, str]  # {filename: content}
    step_outputs: list[str]

    # Code generation specific
    model: str
    ext: str
    filename: str
    program_language: str

    # Tax report specific
    financial_data: dict[str, Any]

    # Error handling
    error: str
    retry_count: int
    max_retries: int  # 2 per step

    # Output
    response_text: str
    buttons: list[dict[str, str]]
    document: bytes | None
    document_name: str
