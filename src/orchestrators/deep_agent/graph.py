"""Deep Agent orchestrator — LangGraph StateGraph for multi-step tasks.

Provides planning + iterative execution for complex code generation
and tax report tasks. Called directly from skill handlers when
complexity classifier detects a complex request.

Graph structure::

    START → plan_task → execute_step → validate_step
                              ↑              │
                              │      ┌───────┴────────┐
                              │      │ success        │ error
                              │      ↓                ↓
                              │  advance_step    review_and_fix
                              │      │                │
                              │      └────────────────┘
                              │      │ more steps ↗   │ retries left → validate_step
                              │      └────────────────┘
                              │              │ no more steps
                              │              ↓
                              │           finalize → END
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.core.observability import observe
from src.orchestrators.deep_agent.nodes import (
    advance_step,
    execute_step,
    finalize,
    plan_task,
    review_and_fix,
    route_after_fix,
    route_after_validate,
    validate_step,
)
from src.orchestrators.deep_agent.state import DeepAgentState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def build_deep_agent_graph() -> StateGraph:
    """Build the deep agent execution graph."""
    graph = StateGraph(DeepAgentState)

    # Nodes
    graph.add_node("plan_task", plan_task)
    graph.add_node("execute_step", execute_step)
    graph.add_node("validate_step", validate_step)
    graph.add_node("review_and_fix", review_and_fix)
    graph.add_node("advance_step", advance_step)
    graph.add_node("finalize", finalize)

    # Edges
    graph.add_edge(START, "plan_task")
    graph.add_edge("plan_task", "execute_step")
    graph.add_edge("execute_step", "validate_step")

    # After validation: fix errors, advance, or finalize
    graph.add_conditional_edges(
        "validate_step",
        route_after_validate,
        {
            "review_and_fix": "review_and_fix",
            "advance_step": "advance_step",
            "finalize": "finalize",
        },
    )

    # After fix: re-validate or move on
    graph.add_conditional_edges(
        "review_and_fix",
        route_after_fix,
        {
            "validate_step": "validate_step",
            "execute_step": "execute_step",
            "finalize": "finalize",
        },
    )

    # Advance → next execute
    graph.add_edge("advance_step", "execute_step")

    # Finalize → END
    graph.add_edge("finalize", END)

    return graph


_deep_agent_graph = None


def _get_deep_agent_graph():
    """Lazily compile with checkpointer."""
    global _deep_agent_graph
    if _deep_agent_graph is not None:
        return _deep_agent_graph

    from src.core.config import settings
    from src.orchestrators.checkpointer import get_checkpointer

    builder = build_deep_agent_graph()
    checkpointer = get_checkpointer() if settings.ff_langgraph_checkpointer else None
    _deep_agent_graph = builder.compile(checkpointer=checkpointer)
    return _deep_agent_graph


class DeepAgentOrchestrator:
    """Orchestrator for complex multi-step tasks.

    Called directly from skill handlers — not registered in DomainRouter.
    """

    @observe(name="deep_agent_run")
    async def run(
        self,
        task_description: str,
        skill_type: str,
        user_id: str,
        family_id: str,
        language: str = "en",
        model: str = "claude-sonnet-4-6",
        ext: str = ".py",
        filename: str = "app.py",
        program_language: str = "",
        financial_data: dict[str, Any] | None = None,
    ) -> SkillResult:
        """Run the deep agent graph and return a SkillResult."""
        import uuid as uuid_mod

        thread_id = f"deep-{user_id}-{uuid_mod.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        initial_state: DeepAgentState = {
            "user_id": user_id,
            "family_id": family_id,
            "language": language,
            "task_description": task_description,
            "skill_type": skill_type,
            "plan": [],
            "current_step_index": 0,
            "files": {},
            "step_outputs": [],
            "model": model,
            "ext": ext,
            "filename": filename,
            "program_language": program_language,
            "financial_data": financial_data or {},
            "error": "",
            "retry_count": 0,
            "max_retries": 2,
            "response_text": "",
            "buttons": [],
            "document": None,
            "document_name": "",
        }

        try:
            result = await _get_deep_agent_graph().ainvoke(initial_state, config)
            return self._build_result(result)
        except Exception as e:
            logger.error("Deep agent graph failed: %s", e, exc_info=True)
            return SkillResult(
                response_text="Complex generation failed. Try a simpler request.",
            )

    def _build_result(self, result: dict[str, Any]) -> SkillResult:
        """Convert graph result to SkillResult."""
        text = result.get("response_text", "")
        buttons = result.get("buttons")
        doc = result.get("document")
        doc_name = result.get("document_name", "")

        return SkillResult(
            response_text=text or "Done.",
            buttons=buttons or None,
            document=doc if isinstance(doc, bytes) else None,
            document_name=doc_name or None,
        )
