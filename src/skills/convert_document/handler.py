"""Convert document skill — file format conversion."""

import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.tools.conversion_service import (
    MAX_INPUT_SIZE,
    ConversionError,
    convert_document,
    detect_source_format,
    get_supported_targets,
    is_supported,
)

logger = logging.getLogger(__name__)

KNOWN_FORMATS = {
    "pdf", "docx", "doc", "txt", "rtf", "odt", "html", "md",
    "xlsx", "xls", "csv", "ods", "pptx",
    "epub", "fb2", "mobi", "djvu",
    "jpg", "jpeg", "png", "tiff",
}

SYSTEM_PROMPT = """\
You are a document conversion assistant. You convert files between formats.
Supported: PDF, DOCX, TXT, RTF, ODT, XLSX, CSV, ODS, XLS, PPTX, \
EPUB, FB2, MOBI, DJVU, HTML, MD, JPG, PNG, TIFF.
Be concise. Use HTML tags for Telegram."""


class ConvertDocumentSkill:
    name = "convert_document"
    intents = ["convert_document"]
    model = "claude-haiku-4-5"

    @observe(name="convert_document")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # 1. Validate file is attached
        file_bytes = message.document_bytes or message.photo_bytes
        filename = message.document_file_name
        mime_type = message.document_mime_type

        # Photos come without document_file_name/mime
        if not message.document_bytes and message.photo_bytes:
            filename = filename or "photo.jpg"
            mime_type = mime_type or "image/jpeg"

        if not file_bytes:
            return SkillResult(
                response_text=(
                    "Please send a file along with your conversion request.\n"
                    "Example: attach a DOCX and write <b>convert to PDF</b>"
                )
            )

        # 2. Extract target format
        target_format = (intent_data.get("target_format") or "").strip().lower()
        if not target_format:
            target_format = _extract_target_from_text(message.text or "")
        if not target_format:
            return SkillResult(
                response_text=(
                    "What format should I convert to?\n"
                    "Example: <b>convert to PDF</b>"
                )
            )

        # Normalize jpeg → jpg
        if target_format == "jpeg":
            target_format = "jpg"

        # 3. Detect source format
        source_format = detect_source_format(filename, mime_type)
        if not source_format:
            return SkillResult(
                response_text="I couldn't determine the file format. "
                "Make sure the file has a proper extension."
            )

        # Normalize jpeg → jpg
        if source_format == "jpeg":
            source_format = "jpg"

        # 4. Check file size
        if len(file_bytes) > MAX_INPUT_SIZE:
            size_mb = len(file_bytes) / (1024 * 1024)
            return SkillResult(
                response_text=f"File is too large ({size_mb:.1f} MB). Maximum: 20 MB."
            )

        # 5. Same format check
        if source_format == target_format:
            return SkillResult(
                response_text=f"The file is already in <b>{target_format.upper()}</b> format."
            )

        # 6. Check if conversion is supported
        if not is_supported(source_format, target_format):
            targets = get_supported_targets(source_format)
            if targets:
                target_list = ", ".join(
                    f"<b>{t.upper()}</b>" for t in sorted(targets)
                )
                return SkillResult(
                    response_text=(
                        f"Can't convert <b>{source_format.upper()}</b> to "
                        f"<b>{target_format.upper()}</b>.\n"
                        f"Supported targets: {target_list}"
                    )
                )
            return SkillResult(
                response_text=f"Format <b>{source_format.upper()}</b> is not supported "
                "for conversion."
            )

        # 7. Perform conversion
        src_filename = filename or f"document.{source_format}"
        try:
            output_bytes, output_name = await convert_document(
                file_bytes, source_format, target_format, src_filename
            )
        except ConversionError as e:
            logger.warning(
                "Conversion failed: %s -> %s: %s", source_format, target_format, e
            )
            return SkillResult(
                response_text=f"Conversion failed: {e}\nTry a different format or check the file."
            )
        except Exception:
            logger.exception("Unexpected conversion error")
            return SkillResult(
                response_text="Something went wrong during conversion. Try again?"
            )

        # 8. Return converted file
        size_kb = len(output_bytes) / 1024
        size_str = (
            f"{size_kb:.0f} KB"
            if size_kb < 1024
            else f"{size_kb / 1024:.1f} MB"
        )
        return SkillResult(
            response_text=(
                f"Converted <b>{source_format.upper()}</b> → "
                f"<b>{target_format.upper()}</b> ({size_str})"
            ),
            document=output_bytes,
            document_name=output_name,
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


def _extract_target_from_text(text: str) -> str:
    """Try to extract target format from user message text."""
    text_lower = text.lower()
    m = re.search(
        r"(?:to|в|into|как|в формат|save as|сохрани как)\s+\.?(\w{2,5})\b",
        text_lower,
    )
    if m:
        candidate = m.group(1)
        if candidate in KNOWN_FORMATS:
            return candidate
    return ""


skill = ConvertDocumentSkill()
