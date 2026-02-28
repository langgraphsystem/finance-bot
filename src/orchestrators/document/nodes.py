"""Document orchestrator graph nodes.

Pipeline: planner → extractor → processor → generator → reviewer
The reviewer drives a conditional edge: quality_ok → END, else → processor
(max 2 revision cycles).

Each node calls Claude Sonnet 4.6 for analysis/generation steps.
All nodes handle errors gracefully, writing a safe fallback into state
so downstream nodes can still produce a partial result.
"""

import logging
from typing import Any

from src.core.llm.clients import generate_text
from src.orchestrators.document.state import DocumentState

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
MAX_REVISIONS = 2


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


async def planner(state: DocumentState) -> dict[str, Any]:
    """Analyse the intent and user message to decide the processing plan.

    Sets ``output_format`` based on intent so downstream nodes know what
    kind of document to produce without repeating the logic.
    """
    intent = state.get("intent", "analyze_document")
    message_text = state.get("message_text", "")
    language = state.get("language", "en")

    logger.info("Document planner: intent=%s", intent)

    # Derive a sensible default output format from the intent
    format_map: dict[str, str] = {
        "generate_invoice_pdf": "pdf",
        "fill_pdf_form": "pdf",
        "fill_template": "docx",
        "generate_document": "docx",
        "generate_presentation": "pptx",
        "generate_spreadsheet": "xlsx",
        "extract_table": "xlsx",
        "merge_documents": "pdf",
        "pdf_operations": "pdf",
        "convert_document": "pdf",
        "compare_documents": "text",
        "summarize_document": "text",
        "analyze_document": "text",
    }
    output_format = format_map.get(intent, "text")

    # Ask the LLM to identify the key steps for this specific request
    if message_text:
        system = (
            "You are a document processing assistant. "
            "Given an intent and user request, briefly describe what steps are needed "
            "to fulfil it (extract → process → generate). Be concise — one sentence per step. "
            f"Respond in: {language}."
        )
        try:
            plan = await generate_text(
                model=_MODEL,
                system=system,
                prompt=f"Intent: {intent}\nRequest: {message_text}",
                max_tokens=256,
            )
            logger.debug("Document plan: %s", plan)
        except Exception as exc:
            logger.warning("Planner LLM call failed: %s", exc)

    return {
        "intent": intent,
        "output_format": output_format,
        "revision_count": state.get("revision_count", 0),
        "quality_ok": False,
    }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


async def extractor(state: DocumentState) -> dict[str, Any]:
    """Extract text, tables, and metadata from the input document(s).

    In production this calls the document conversion service / OCR pipeline.
    For now it uses Claude Sonnet to analyse any text payload and returns
    structured extraction results.
    """
    intent = state.get("intent", "")
    message_text = state.get("message_text", "")
    input_files = state.get("input_files", [])
    language = state.get("language", "en")

    logger.info("Document extractor: %d input file(s)", len(input_files))

    if not message_text and not input_files:
        return {
            "extracted_text": "",
            "extracted_tables": [],
            "extracted_metadata": {},
        }

    # Build a representation of what we received for the LLM to reason about
    file_summary = ""
    if input_files:
        parts = []
        for f in input_files:
            name = f.get("filename", "unknown")
            mime = f.get("mime_type", "application/octet-stream")
            size = len(f.get("bytes", b""))
            parts.append(f"{name} ({mime}, {size} bytes)")
        file_summary = "Input files:\n" + "\n".join(f"- {p}" for p in parts)

    user_content = "\n\n".join(filter(None, [message_text, file_summary]))

    system = (
        "You are a document extraction engine. "
        "Given a description of the user's request and any input files, "
        "identify and list: (1) the key textual content to extract, "
        "(2) any tabular data present, (3) relevant metadata (author, date, title). "
        "Return a structured plain-text summary. "
        f"Respond in: {language}."
    )

    try:
        extracted = await generate_text(
            model=_MODEL,
            system=system,
            prompt=f"Intent: {intent}\n\n{user_content}",
            max_tokens=1024,
        )
    except Exception as exc:
        logger.warning("Extractor LLM call failed: %s", exc)
        extracted = user_content

    return {
        "extracted_text": extracted,
        "extracted_tables": [],
        "extracted_metadata": {},
    }


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


async def processor(state: DocumentState) -> dict[str, Any]:
    """Transform extracted content: match template fields, compute diffs, etc.

    On revision cycles ``revision_feedback`` from the reviewer is injected
    into the prompt so the model can correct specific issues.
    """
    intent = state.get("intent", "")
    extracted_text = state.get("extracted_text", "")
    template_file = state.get("template_file")
    language = state.get("language", "en")
    revision_feedback = state.get("revision_feedback", "")
    revision_count = state.get("revision_count", 0)

    logger.info("Document processor: intent=%s revision=%d", intent, revision_count)

    template_hint = ""
    if template_file:
        name = template_file.get("filename", "template")
        template_hint = f"\nTemplate provided: {name}"

    feedback_hint = ""
    if revision_feedback:
        feedback_hint = f"\n\nRevision feedback to address:\n{revision_feedback}"

    system = (
        "You are a document processing engine. "
        "Transform the extracted content into structured, ready-to-use data "
        "that can be fed directly into a document generator. "
        "Match fields to template placeholders if a template is provided. "
        "For comparison intents, highlight key differences. "
        "For analysis intents, produce a structured summary. "
        f"Respond in: {language}."
    )

    user_content = (
        f"Intent: {intent}{template_hint}\n\nExtracted content:\n{extracted_text}{feedback_hint}"
    )

    try:
        processed = await generate_text(
            model=_MODEL,
            system=system,
            prompt=user_content,
            max_tokens=2048,
        )
    except Exception as exc:
        logger.warning("Processor LLM call failed: %s", exc)
        processed = extracted_text

    return {"processed_content": processed}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


async def generator(state: DocumentState) -> dict[str, Any]:
    """Generate the output document from processed content.

    For text-output intents the result is stored in ``response_text``.
    For binary outputs (pdf, docx, xlsx) the node would invoke the
    conversion service; here we produce the source markup/content as
    ``response_text`` and leave ``output_bytes`` None (wired up in prod).
    """
    intent = state.get("intent", "")
    processed_content = state.get("processed_content", "")
    output_format = state.get("output_format", "text")
    language = state.get("language", "en")
    message_text = state.get("message_text", "")

    logger.info("Document generator: intent=%s format=%s", intent, output_format)

    if not processed_content and not message_text:
        return {
            "output_bytes": None,
            "output_filename": None,
            "response_text": "No content to generate a document from.",
        }

    format_instructions = {
        "pdf": "Format the output as clean HTML that will be rendered to PDF via WeasyPrint.",
        "docx": "Format the output as structured plain text with clear section headers.",
        "xlsx": "Format the output as a CSV-style table with header row.",
        "pptx": (
            "Format the output as slide outlines: one section per slide with a title and bullets."
        ),
        "text": "Format the output as a concise plain-text document.",
    }
    format_hint = format_instructions.get(output_format, format_instructions["text"])

    system = (
        "You are a document generation engine. "
        "Produce a complete, well-structured document from the processed content. "
        f"{format_hint} "
        "Use HTML tags (<b>, <i>, <ul>, <li>) for structure where applicable. "
        f"Respond in: {language}."
    )

    user_content = f"Intent: {intent}\n\nContent to render:\n{processed_content}"

    try:
        generated = await generate_text(
            model=_MODEL,
            system=system,
            prompt=user_content,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.warning("Generator LLM call failed: %s", exc)
        generated = processed_content

    # Derive a filename from intent + format
    filename_map: dict[str, str] = {
        "generate_invoice_pdf": "invoice",
        "fill_template": "filled_template",
        "generate_document": "document",
        "generate_presentation": "presentation",
        "generate_spreadsheet": "spreadsheet",
        "extract_table": "extracted_table",
        "merge_documents": "merged",
    }
    stem = filename_map.get(intent, "output")
    output_filename = f"{stem}.{output_format}" if output_format != "text" else None

    return {
        "output_bytes": None,  # populated by conversion service in prod
        "output_filename": output_filename,
        "response_text": generated,
    }


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


async def reviewer(state: DocumentState) -> dict[str, Any]:
    """Quality-check the generated output.

    Evaluates whether the document meets basic completeness and accuracy
    criteria. Sets ``quality_ok`` and, on failure, populates
    ``revision_feedback`` with specific issues to fix.
    """
    intent = state.get("intent", "")
    response_text = state.get("response_text", "")
    revision_count = state.get("revision_count", 0)

    logger.info("Document reviewer: intent=%s revision=%d", intent, revision_count)

    # Automatically pass on max revisions to avoid infinite loops
    if revision_count >= MAX_REVISIONS:
        logger.info("Max revisions reached — accepting output as-is")
        return {"quality_ok": True, "revision_feedback": ""}

    if not response_text or len(response_text.strip()) < 20:
        return {
            "quality_ok": False,
            "revision_feedback": "Output is empty or too short to be useful.",
            "revision_count": revision_count + 1,
        }

    system = (
        "You are a document quality reviewer. "
        "Given the intent and generated document, decide if it is complete and correct. "
        "Reply with exactly one of:\n"
        "  PASS — the document is acceptable.\n"
        "  FAIL: <specific issues to fix>\n"
        "Be concise. One line only."
    )

    snippet = response_text[:1500]
    user_content = f"Intent: {intent}\n\nGenerated document (first 1500 chars):\n{snippet}"

    try:
        verdict = await generate_text(
            model=_MODEL,
            system=system,
            prompt=user_content,
            max_tokens=128,
        )
        verdict = verdict.strip()
    except Exception as exc:
        logger.warning("Reviewer LLM call failed: %s", exc)
        # On LLM error, accept the output rather than blocking delivery
        return {"quality_ok": True, "revision_feedback": ""}

    if verdict.upper().startswith("PASS"):
        return {"quality_ok": True, "revision_feedback": ""}

    # Extract feedback after "FAIL:"
    feedback = verdict[verdict.find(":") + 1 :].strip() if ":" in verdict else verdict
    return {
        "quality_ok": False,
        "revision_feedback": feedback,
        "revision_count": revision_count + 1,
    }


# ---------------------------------------------------------------------------
# Conditional edge
# ---------------------------------------------------------------------------


def should_revise(state: DocumentState) -> str:
    """Conditional edge after reviewer.

    Returns ``"done"`` when quality is acceptable or max revisions reached,
    otherwise ``"revise"`` to loop back to the processor node.
    """
    if state.get("quality_ok", False):
        return "done"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "done"
    return "revise"
