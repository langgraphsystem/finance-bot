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
        "header": "Document Analysis",
        "pages": "Pages",
        "size": "Size",
        "image_via_vision": "image — analyzed via vision",
        "scanned_via_vision": "scanned PDF — analyzed via vision",
        "truncated": "document truncated for analysis",
        "vision_failed": "Failed to analyze the document. Try a clearer image.",
        "text_empty": "Could not extract text from this document. It may be empty or corrupted.",
        "analysis_failed": "Failed to analyze the document. Please try again.",
    },
    "ru": {
        "no_file": "Отправьте документ — фото, PDF, Word или Excel.",
        "header": "Анализ документа",
        "pages": "Страниц",
        "size": "Размер",
        "image_via_vision": "изображение — анализ через vision",
        "scanned_via_vision": "сканированный PDF — анализ через vision",
        "truncated": "документ усечён для анализа",
        "vision_failed": "Не удалось проанализировать документ. Попробуйте более чёткое фото.",
        "text_empty": "Не удалось извлечь текст. Документ может быть пустым или повреждённым.",
        "analysis_failed": "Не удалось проанализировать документ. Попробуйте ещё раз.",
    },
    "es": {
        "no_file": "Envíe un documento — foto, PDF, Word o Excel.",
        "header": "Análisis del documento",
        "pages": "Páginas",
        "size": "Tamaño",
        "image_via_vision": "imagen — analizada por visión",
        "scanned_via_vision": "PDF escaneado — analizado por visión",
        "truncated": "documento truncado para análisis",
        "vision_failed": "No se pudo analizar el documento. Intente con una imagen más clara.",
        "text_empty": "No se pudo extraer texto. El documento puede estar vacío o dañado.",
        "analysis_failed": "No se pudo analizar el documento. Inténtelo de nuevo.",
    },
}
register_strings("analyze_document", _STRINGS)

SYSTEM_PROMPT = """\
You are a document analysis assistant. You analyze uploaded documents \
and answer questions about their content.
Be concise and reference page numbers when possible. Use HTML tags for Telegram.
{lang_instruction}"""

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
{lang_instruction}
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
{lang_instruction}
Use HTML tags (<b>, <i>, <code>) for formatting. Be concise."""


def _lang_instruction(lang: str) -> str:
    """Return a language instruction for the LLM."""
    if lang == "en":
        return ""
    lang_names = {
        "ru": "Russian", "es": "Spanish", "fr": "French", "de": "German",
        "pt": "Portuguese", "it": "Italian", "uk": "Ukrainian", "pl": "Polish",
        "tr": "Turkish", "ar": "Arabic", "zh": "Chinese", "ja": "Japanese",
        "ko": "Korean", "hi": "Hindi", "ky": "Kyrgyz",
    }
    name = lang_names.get(lang, lang)
    return f"IMPORTANT: Respond entirely in {name}."


async def _analyze_via_vision(
    file_bytes: bytes,
    filename: str,
    question: str | None,
    is_image: bool,
    lang: str = "en",
) -> str:
    """Analyze an image or scanned PDF using Gemini vision."""
    import base64

    from src.core.llm.clients import google_client

    q_section = f"User question: {question}" if question else ""
    q_instruction = f"Focus your analysis on answering: {question}" if question else ""
    prompt = VISION_PROMPT.format(
        question_section=q_section,
        question_instruction=q_instruction,
        lang_instruction=_lang_instruction(lang),
    )

    client = google_client()
    parts: list = [prompt]

    if is_image:
        # Direct image — send as-is
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpeg"
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "tiff": "image/tiff",
            "heic": "image/heic",
        }
        mime = mime_map.get(ext, "image/jpeg")
        parts.append(
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(file_bytes).decode()}}
        )
    else:
        # Scanned PDF — render pages to images
        from src.tools.document_reader import extract_pages_as_images

        images = await extract_pages_as_images(file_bytes, filename)
        if not images:
            return "Could not render PDF pages for analysis."
        for img_bytes in images[:5]:
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

        lang = context.language or "en"
        ns = "analyze_document"

        if not file_bytes:
            return SkillResult(
                response_text=t_cached(_STRINGS, "no_file", lang, ns)
            )

        question = intent_data.get("search_query") or intent_data.get("query")

        # Handle images directly via vision
        if message.photo_bytes and not message.document_bytes:
            filename = filename if filename != "document" else "photo.jpg"
            mime_type = mime_type or "image/jpeg"

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        is_image = ext in ("jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "heic")
        file_size_kb = len(file_bytes) / 1024
        file_size = (
            f"{file_size_kb:.0f} KB" if file_size_kb < 1024 else f"{file_size_kb / 1024:.1f} MB"
        )

        # Check if scanned PDF (needs vision path)
        is_scanned = False
        if ext == "pdf":
            is_scanned = await is_scanned_pdf(file_bytes)

        # Vision path: images, scanned PDFs, photos
        use_vision = is_scanned or is_image

        if use_vision:
            logger.info(
                "Using vision analysis for %s (image=%s, scanned=%s)",
                filename, is_image, is_scanned,
            )
            try:
                analysis = await _analyze_via_vision(
                    file_bytes, filename, question, is_image, lang,
                )
            except Exception as e:
                logger.exception("Vision analysis failed: %s", e)
                return SkillResult(
                    response_text=t_cached(_STRINGS, "vision_failed", lang, ns)
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
                        response_text=t_cached(_STRINGS, "text_empty", lang, ns)
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
            li = _lang_instruction(lang)

            prompt = ANALYSIS_PROMPT.format(
                filename=filename,
                page_count=page_count,
                file_size=file_size,
                text=text,
                question_section=q_section,
                question_instruction=q_instruction,
                lang_instruction=li,
            )

            try:
                analysis = await generate_text(
                    model="claude-sonnet-4-6",
                    system=SYSTEM_PROMPT.format(lang_instruction=li),
                    prompt=prompt,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.exception("LLM analysis failed: %s", e)
                return SkillResult(
                    response_text=t_cached(_STRINGS, "analysis_failed", lang, ns)
                )

        # Build header
        h_title = t_cached(_STRINGS, "header", lang, ns)
        h_size = t_cached(_STRINGS, "size", lang, ns)
        header = f"<b>{h_title}</b>: {filename}\n"
        if ext == "pdf":
            try:
                pc = await get_page_count(file_bytes, filename)
                h_pages = t_cached(_STRINGS, "pages", lang, ns)
                header += f"{h_pages}: {pc} | {h_size}: {file_size}\n"
            except Exception:
                header += f"{h_size}: {file_size}\n"
        else:
            header += f"{h_size}: {file_size}\n"

        if is_image:
            header += f"<i>({t_cached(_STRINGS, 'image_via_vision', lang, ns)})</i>\n"
        elif is_scanned:
            header += f"<i>({t_cached(_STRINGS, 'scanned_via_vision', lang, ns)})</i>\n"
        if "truncated" in dir() and truncated:
            header += f"<i>({t_cached(_STRINGS, 'truncated', lang, ns)})</i>\n"

        return SkillResult(response_text=f"{header}\n{analysis}")

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = AnalyzeDocumentSkill()
