"""Deep AI analysis of documents with Q&A."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.tools.document_reader import (
    extract_text,
    get_page_count,
    is_scanned_pdf,
)

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "no_file": "Send me a document — photo, PDF, Word, or Excel.",
    },
    "ru": {
        "no_file": ("Отправьте документ — фото, PDF, Word или Excel."),
    },
    "es": {
        "no_file": "Envíe un documento — foto, PDF, Word o Excel.",
    },
}
register_strings("analyze_document", _STRINGS)

SYSTEM_PROMPT = """\
You are a document analysis assistant. You analyze uploaded documents \
and answer questions about their content.
Be concise and reference page numbers when possible. Use HTML tags for Telegram."""

ANALYSIS_PROMPT = """\
Analyze the following document and provide a structured summary.

Document metadata:
- Filename: {filename}
- Pages: {page_count}
- Size: {file_size}

{question_section}

Document text:
---
{text}
---

Provide your analysis in this structure:
1. Document type and purpose
2. Key information and data points
3. Important dates, amounts, or entities
4. Summary (2-3 sentences)

{question_instruction}
Use HTML tags (<b>, <i>, <code>) for formatting. Be concise."""

VISION_PROMPT = """\
Analyze this scanned document image. Extract and summarize the key information.

{question_section}

Provide:
1. Document type and purpose
2. Key text and data visible
3. Important dates, amounts, or entities
4. Summary

{question_instruction}
Use HTML tags (<b>, <i>, <code>) for formatting. Be concise."""


async def _analyze_scanned_pdf(file_bytes: bytes, filename: str, question: str | None) -> str:
    """Analyze a scanned PDF using Gemini vision on page images."""
    import base64

    from src.core.llm.clients import google_client
    from src.tools.document_reader import extract_pages_as_images

    images = await extract_pages_as_images(file_bytes, filename)
    if not images:
        return "Could not render PDF pages for analysis."

    # Limit to first 5 pages to stay within token budget
    images = images[:5]

    q_section = f"User question: {question}" if question else ""
    q_instruction = f"Focus your analysis on answering: {question}" if question else ""
    prompt = VISION_PROMPT.format(
        question_section=q_section,
        question_instruction=q_instruction,
    )

    client = google_client()
    parts: list = [prompt]
    for img_bytes in images:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(img_bytes).decode(),
                }
            }
        )

    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=parts,
    )
    return response.text or "Analysis produced no output."


class AnalyzeDocumentSkill:
    name = "analyze_document"
    intents = ["analyze_document"]
    model = "claude-sonnet-4-6"

    @observe(name="analyze_document")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        file_bytes = message.document_bytes or message.photo_bytes
        filename = message.document_file_name or "document"
        mime_type = message.document_mime_type or ""

        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(
                response_text=t_cached(_STRINGS, "no_file", lang, "analyze_document")
            )

        question = intent_data.get("search_query") or intent_data.get("query")

        # Handle images directly via vision
        if message.photo_bytes and not message.document_bytes:
            filename = filename if filename != "document" else "photo.jpg"
            mime_type = mime_type or "image/jpeg"

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        file_size_kb = len(file_bytes) / 1024
        file_size = (
            f"{file_size_kb:.0f} KB" if file_size_kb < 1024 else f"{file_size_kb / 1024:.1f} MB"
        )

        # Check if scanned PDF (needs vision path)
        is_scanned = False
        if ext == "pdf":
            is_scanned = await is_scanned_pdf(file_bytes)

        if is_scanned:
            logger.info("Scanned PDF detected, using vision analysis for %s", filename)
            try:
                analysis = await _analyze_scanned_pdf(file_bytes, filename, question)
            except Exception as e:
                logger.exception("Vision analysis failed: %s", e)
                return SkillResult(
                    response_text="Failed to analyze the scanned document. Try a clearer scan."
                )
        else:
            # Text-based analysis via Claude Sonnet
            try:
                text = await extract_text(file_bytes, filename, mime_type)
            except Exception as e:
                logger.warning("Text extraction failed: %s", e)
                text = ""

            if not text.strip():
                if ext in ("pdf", "docx", "doc", "xlsx", "txt", "csv"):
                    return SkillResult(
                        response_text="Could not extract text from this document. "
                        "It may be empty or corrupted."
                    )
                return SkillResult(
                    response_text=f"Unsupported format (<b>{ext}</b>) for text analysis. "
                    "Supported: PDF, DOCX, XLSX, TXT, CSV."
                )

            # Get page count
            try:
                page_count = await get_page_count(file_bytes, filename)
            except Exception:
                page_count = 1

            # Truncate text to stay within token budget (~100K chars ~ 25K tokens)
            max_chars = 100_000
            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars]
                truncated = True

            q_section = f"User question: {question}" if question else ""
            q_instruction = f"Focus your analysis on answering: {question}" if question else ""

            prompt = ANALYSIS_PROMPT.format(
                filename=filename,
                page_count=page_count,
                file_size=file_size,
                text=text,
                question_section=q_section,
                question_instruction=q_instruction,
            )

            try:
                analysis = await generate_text(
                    model="claude-sonnet-4-6",
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.exception("LLM analysis failed: %s", e)
                return SkillResult(
                    response_text="Failed to analyze the document. Please try again."
                )

        # Build header
        header = f"<b>Document Analysis</b>: {filename}\n"
        if ext == "pdf":
            try:
                pc = await get_page_count(file_bytes, filename)
                header += f"Pages: {pc} | Size: {file_size}\n"
            except Exception:
                header += f"Size: {file_size}\n"
        else:
            header += f"Size: {file_size}\n"

        if is_scanned:
            header += "<i>(scanned PDF — analyzed via vision)</i>\n"
        if "truncated" in dir() and truncated:
            header += "<i>(document truncated for analysis)</i>\n"

        return SkillResult(response_text=f"{header}\n{analysis}")

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = AnalyzeDocumentSkill()
