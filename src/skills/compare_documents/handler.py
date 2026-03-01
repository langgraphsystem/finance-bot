"""Compare documents and find differences \u2014 semantic and structural."""

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
        "no_file": "Upload the documents you want to compare.",
    },
    "ru": {
        "no_file": "Отправьте документы для сравнения.",
    },
    "es": {
        "no_file": "Suba los documentos que desea comparar.",
    },
}
register_strings("compare_documents", _STRINGS)

COMPARE_SYSTEM_PROMPT = """\
You are a document comparison specialist. You receive extracted text from one or
two documents and analyze differences, similarities, and key changes.

Output format (Telegram HTML):
1. <b>Overview</b> — one-sentence summary of the comparison
2. <b>Key Differences</b> — bulleted list of significant changes
3. <b>Similarities</b> — brief note on what stayed the same
4. <b>Risk/Action Items</b> — anything the user should pay attention to

Be precise and concise. Quote specific text when pointing out differences.
If only one document is provided with a question, analyze that document
in the context of the question."""


class CompareDocumentsSkill:
    name = "compare_documents"
    intents = ["compare_documents"]
    model = "claude-sonnet-4-6"

    @observe(name="compare_documents")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.tools.document_reader import extract_text

        file_bytes = message.document_bytes or message.photo_bytes
        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(
                response_text=t_cached(_STRINGS, "no_file", lang, "compare_documents")
            )

        filename = message.document_file_name or "document"
        mime_type = message.document_mime_type or "application/octet-stream"

        if not message.document_bytes and message.photo_bytes:
            filename = filename if filename != "document" else "photo.jpg"
            mime_type = "image/jpeg"

        # Extract text from the uploaded document
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
                    "If it's a scanned PDF, try uploading a text-based version."
                )
            )

        # Build comparison prompt
        user_question = (intent_data.get("description") or message.text or "").strip()
        question_part = f"\nUser's question: {user_question}" if user_question else ""

        # Check if a second document reference exists in intent
        second_doc_ref = intent_data.get("second_document_text") or ""

        if second_doc_ref:
            prompt = (
                f"Compare these two documents:\n\n"
                f"--- DOCUMENT 1 ---\n{doc_text[:15000]}\n\n"
                f"--- DOCUMENT 2 ---\n{second_doc_ref[:15000]}"
                f"{question_part}"
            )
        else:
            prompt = (
                f"Analyze this document and provide a detailed comparison/review:\n\n"
                f"--- DOCUMENT ---\n{doc_text[:30000]}"
                f"{question_part}\n\n"
                "If the user is asking to compare with something, identify what "
                "they want to compare and provide the best analysis possible from "
                "the available text."
            )

        try:
            analysis = await generate_text(
                model=self.model,
                system=COMPARE_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("LLM comparison failed: %s", e)
            return SkillResult(response_text="Something went wrong during comparison. Try again?")

        doc_size_kb = len(file_bytes) / 1024
        text_chars = len(doc_text)

        header = (
            f"<b>Document Analysis</b> — {filename}\n"
            f"<i>{doc_size_kb:.0f} KB, {text_chars:,} characters extracted</i>\n\n"
        )

        return SkillResult(response_text=header + analysis)

    def get_system_prompt(self, context: SessionContext) -> str:
        return COMPARE_SYSTEM_PROMPT


skill = CompareDocumentsSkill()
