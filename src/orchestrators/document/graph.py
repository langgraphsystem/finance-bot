"""Document orchestrator — LangGraph StateGraph.

Nodes: planner → extractor → processor → generator → reviewer
Handles: analyze_document, fill_template, fill_pdf_form, generate_invoice_pdf,
         merge_documents, pdf_operations, generate_spreadsheet, extract_table,
         compare_documents, summarize_document, generate_document,
         generate_presentation, convert_document, list_documents, search_documents

The reviewer drives a conditional revision loop (max 2 cycles):
  quality_ok  → END
  not ok      → processor (re-runs with revision_feedback injected)
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.core.config import settings
from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.orchestrators.document.nodes import (
    extractor,
    generator,
    planner,
    processor,
    reviewer,
    should_revise,
)
from src.orchestrators.document.state import DocumentState
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


def build_document_graph() -> StateGraph:
    """Build the document orchestrator graph."""
    graph = StateGraph(DocumentState)

    graph.add_node("planner", planner)
    graph.add_node("extractor", extractor)
    graph.add_node("processor", processor)
    graph.add_node("generator", generator)
    graph.add_node("reviewer", reviewer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "extractor")
    graph.add_edge("extractor", "processor")
    graph.add_edge("processor", "generator")
    graph.add_edge("generator", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        should_revise,
        {
            "revise": "processor",
            "done": END,
        },
    )

    return graph


def _compile_document_graph():
    """Compile the document graph with optional checkpointer."""
    builder = build_document_graph()
    if settings.ff_langgraph_checkpointer:
        from src.orchestrators.checkpointer import get_checkpointer

        return builder.compile(checkpointer=get_checkpointer())
    return builder.compile()


# Alias for external callers (e.g. tests)
def build_document_orchestrator():
    """Factory — returns a compiled document orchestrator graph."""
    return _compile_document_graph()


# Lazy-compiled graph (singleton)
_document_graph = None


def _get_document_graph():
    """Lazy-init the document graph on first use."""
    global _document_graph
    if _document_graph is None:
        _document_graph = _compile_document_graph()
    return _document_graph


class DocumentOrchestrator:
    """Document domain orchestrator — multi-step LangGraph pipeline.

    Routes all ``Domain.document`` intents through a planner → extractor
    → processor → generator → reviewer graph with an optional revision loop.

    Intents that do not require multi-step processing fall through to the
    AgentRouter (e.g. ``list_documents``, ``search_documents``).
    """

    # Intents that benefit from the full orchestration pipeline
    _GRAPH_INTENTS: frozenset[str] = frozenset(
        {
            "analyze_document",
            "fill_template",
            "fill_pdf_form",
            "generate_invoice_pdf",
            "merge_documents",
            "pdf_operations",
            "generate_spreadsheet",
            "extract_table",
            "compare_documents",
            "summarize_document",
            "generate_document",
            "generate_presentation",
            "convert_document",
            "scan_document",
        }
    )

    def __init__(self, agent_router: Any = None):
        self._agent_router = agent_router

    async def invoke(
        self,
        intent: str,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Route document intents through the graph or directly to skills."""
        if intent in self._GRAPH_INTENTS:
            try:
                # Build input_files from message attachments
                input_files: list[dict] = []
                if message.document_bytes:
                    input_files.append(
                        {
                            "bytes": message.document_bytes,
                            "filename": message.document_file_name or "document",
                            "mime_type": message.document_mime_type or "application/octet-stream",
                        }
                    )
                elif message.photo_bytes:
                    input_files.append(
                        {
                            "bytes": message.photo_bytes,
                            "filename": "photo.jpg",
                            "mime_type": "image/jpeg",
                        }
                    )

                initial_state: DocumentState = {
                    "intent": intent,
                    "message_text": message.text or "",
                    "user_id": context.user_id,
                    "family_id": context.family_id,
                    "language": context.language or "en",
                    "input_files": input_files,
                    "template_file": None,
                    "extracted_text": "",
                    "extracted_tables": [],
                    "extracted_metadata": {},
                    "processed_content": "",
                    "output_bytes": None,
                    "output_filename": None,
                    "output_format": "text",
                    "quality_ok": False,
                    "revision_feedback": "",
                    "revision_count": 0,
                    "response_text": "",
                }

                config: dict[str, Any] = {}
                if settings.ff_langgraph_checkpointer:
                    thread_id = f"document-{context.user_id}-{intent}-{message.id}"
                    config = {"configurable": {"thread_id": thread_id}}

                result = await _get_document_graph().ainvoke(initial_state, config or None)

                text = result.get("response_text", "")
                output_filename = result.get("output_filename")
                output_bytes = result.get("output_bytes")

                if output_bytes and output_filename:
                    return SkillResult(
                        response_text=text or f"Document ready: {output_filename}",
                        document=output_bytes,
                        document_name=output_filename,
                    )
                if text:
                    return SkillResult(response_text=text)

            except Exception as exc:
                logger.warning(
                    "Document graph failed for intent=%s, falling back: %s",
                    intent,
                    exc,
                )

        # Fallback: delegate to AgentRouter for simple or unrecognised intents
        if self._agent_router:
            return await self._agent_router.route(intent, message, context, intent_data)

        return SkillResult(response_text="Document feature is being set up.")
