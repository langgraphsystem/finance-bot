"""Program orchestrator — deep-agent code generation via LangGraph.

Used for complex requests: multi-component, full-stack, architectural.
Simple requests (< 80 words, single component) use the existing
GenerateProgramSkill directly.

Graph::

    START → planner → generate_code → test_sandbox → review_quality
                            ↑               (route_after_review)
                            └── revise ─────────────┘ (max 2)
                                               ↓ finalize
                                             END
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.complexity_router import classify_complexity
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.resilience import save_to_dlq
from src.orchestrators.program.nodes import (
    finalize,
    generate_code,
    planner,
    review_quality,
    route_after_review,
    test_sandbox,
)
from src.orchestrators.program.state import ProgramState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def _build_program_graph() -> StateGraph:
    """Build and compile the program deep-agent graph."""
    graph = StateGraph(ProgramState)

    graph.add_node("planner", planner)
    graph.add_node("generate_code", generate_code)
    graph.add_node("test_sandbox", test_sandbox)
    graph.add_node("review_quality", review_quality)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "generate_code")
    graph.add_edge("generate_code", "test_sandbox")
    graph.add_edge("test_sandbox", "review_quality")
    graph.add_conditional_edges(
        "review_quality",
        route_after_review,
        {"generate_code": "generate_code", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile()


# Lazy singleton
_program_graph = None


def _get_program_graph():
    global _program_graph
    if _program_graph is None:
        _program_graph = _build_program_graph()
    return _program_graph


class ProgramOrchestrator:
    """Deep-agent orchestrator for complex code generation requests.

    Selectively activates based on complexity classification:
    - Simple requests → delegates to GenerateProgramSkill directly
    - Complex requests → runs ProgramOrchestrator LangGraph
    """

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.agents.complexity_router import classify_complexity

        message_text = message.text or ""

        # Simple requests → use existing fast skill path
        if not classify_complexity(message_text, intent):  # noqa: SIM102
            from src.skills.generate_program.handler import skill as generate_skill

            logger.debug(
                "program orchestrator: simple request, delegating to GenerateProgramSkill"
            )
            return await generate_skill.execute(message, context, intent_data)

        logger.info(
            "program orchestrator: complex request, running deep-agent graph (user=%s)",
            context.user_id,
        )

        initial_state: ProgramState = {
            "intent": intent,
            "user_id": context.user_id,
            "family_id": context.family_id or "",
            "language": context.language or "en",
            "message_text": message_text,
            "requirements": intent_data.get("program_description") or message_text,
            "program_language": (
                intent_data.get("program_language") or ""
            ).lower().strip(),
            "code": "",
            "filename": "program.py",
            "exec_result": None,
            "sandbox_url": None,
            "quality_issues": [],
            "revision_count": 0,
            "response_text": "",
        }

        try:
            result = await _get_program_graph().ainvoke(initial_state)
            response_text = result.get("response_text", "")

            prog_id = result.get("_prog_id", "")
            buttons = []
            if prog_id:
                buttons = [
                    {"text": "📄 Code", "callback": f"show_code:{prog_id}"},
                ]

            # Mem0 background task
            from src.orchestrators.program.nodes import mem0_background
            import asyncio
            asyncio.create_task(mem0_background(result))

            return SkillResult(
                response_text=response_text or "Program generated.",
                buttons=buttons or None,
            )

        except Exception as e:
            logger.exception("ProgramOrchestrator graph failed: %s", e)
            try:
                await save_to_dlq(
                    graph_name="program",
                    thread_id=f"program-{context.user_id}",
                    user_id=context.user_id,
                    family_id=context.family_id or "",
                    error=str(e),
                    state={"message_text": message_text[:500]},
                )
            except Exception:
                pass
            return SkillResult(
                response_text="Failed to generate program. Try a simpler request."
            )
