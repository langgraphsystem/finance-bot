"""Summarize any document with cited key facts."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "no_file": "Send me a document to summarize — PDF, Word, or image.",
    },
    "ru": {
        "no_file": ("Отправьте документ для резюме — PDF, Word или фото."),
    },
    "es": {
        "no_file": "Envíe un documento para resumir — PDF, Word o imagen.",
    },
}
register_strings("summarize_document", _STRINGS)

SUMMARIZE_SYSTEM_PROMPT = """\
You are a document summarization specialist. You produce clear, actionable summaries
from extracted document text.

Output format (Telegram HTML):

<b>Executive Summary</b>
One paragraph capturing the document's purpose and main conclusion.

<b>Key Points</b>
- Bulleted list of the most important facts, with page references where possible
- Include specific numbers, dates, names, and amounts

<b>Important Dates & Amounts</b>
- Any deadlines, monetary values, or dates mentioned

<b>Action Items</b>
- Things the reader should do or decisions to make based on this document

Be concise but thorough. Never fabricate information not present in the source text.
If the document is short, keep the summary proportionally brief."""


class SummarizeDocumentSkill:
    name = "summarize_document"
    intents = ["summarize_document"]
    model = "claude-sonnet-4-6"

    @observe(name="summarize_document")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.tools.document_reader import extract_text, get_page_count

        file_bytes = message.document_bytes or message.photo_bytes
        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(
                response_text=t_cached(_STRINGS, "no_file", lang, "summarize_document")
            )

        filename = message.document_file_name or "document"
        mime_type = message.document_mime_type or "application/octet-stream"

        if not message.document_bytes and message.photo_bytes:
            filename = filename if filename != "document" else "photo.jpg"
            mime_type = "image/jpeg"

        # Extract text
        try:
            doc_text = await extract_text(file_bytes, filename, mime_type)
        except Exception as e:
            logger.warning("Text extraction failed for %s: %s", filename, e)
            return SkillResult(
                response_text="Could not read the document. Make sure it's a supported format."
            )

        if not doc_text.strip():
            return SkillResult(
                response_text=(
                    "Could not extract text from the document. "
                    "If it's a scanned image or PDF, try a text-based version."
                )
            )

        # Get page count for context
        try:
            pages = await get_page_count(file_bytes, filename)
        except Exception:
            pages = 1

        # Build prompt with document metadata
        text_chars = len(doc_text)
        focus_hint = intent_data.get("description") or ""
        focus_part = f"\nUser's focus: {focus_hint}" if focus_hint.strip() else ""

        # Truncate very long documents to fit token budget
        max_chars = 60_000
        truncated = False
        if len(doc_text) > max_chars:
            doc_text = doc_text[:max_chars]
            truncated = True

        prompt = (
            f"Summarize this document ({pages} page(s), {text_chars:,} characters):\n\n"
            f"--- DOCUMENT: {filename} ---\n{doc_text}"
        )
        if truncated:
            prompt += "\n[...document truncated due to length...]"
        prompt += focus_part

        try:
            summary = await generate_text(
                model=self.model,
                system=SUMMARIZE_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("LLM summarization failed: %s", e)
            return SkillResult(
                response_text="Something went wrong during summarization. Try again?"
            )

        doc_size_kb = len(file_bytes) / 1024
        header = f"<b>Summary</b> — {filename}\n<i>{pages} page(s), {doc_size_kb:.0f} KB"
        if truncated:
            header += " (truncated)"
        header += "</i>\n\n"

        return SkillResult(response_text=header + summary)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SUMMARIZE_SYSTEM_PROMPT


skill = SummarizeDocumentSkill()
