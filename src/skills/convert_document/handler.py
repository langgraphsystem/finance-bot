"""Convert document skill — file format conversion."""

import base64
import io
import json
import logging
import re
import zipfile
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
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
    "pdf",
    "docx",
    "doc",
    "txt",
    "rtf",
    "odt",
    "html",
    "md",
    "xlsx",
    "xls",
    "csv",
    "ods",
    "pptx",
    "epub",
    "fb2",
    "mobi",
    "djvu",
    "jpg",
    "jpeg",
    "png",
    "tiff",
}

BATCH_KEY_PREFIX = "doc_batch_convert"
BATCH_TTL = 1800  # 30 minutes
MAX_BATCH = 10

BATCH_TRIGGERS = {
    "convert all",
    "конвертируй всё",
    "конвертируй все",
    "batch convert",
    "convert them all",
    "convert them",
    "конвертировать все",
    "конвертировать всё",
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
        file_bytes = message.document_bytes or message.photo_bytes
        filename = message.document_file_name
        mime_type = message.document_mime_type
        text = (message.text or "").strip()

        # Photos come without document_file_name/mime
        if not message.document_bytes and message.photo_bytes:
            filename = filename or "photo.jpg"
            mime_type = mime_type or "image/jpeg"

        batch_key = f"{BATCH_KEY_PREFIX}:{context.user_id}"
        text_lower = text.lower()

        # --- Batch trigger: no file, but user says "convert all to PDF" ---
        wants_batch = any(trigger in text_lower for trigger in BATCH_TRIGGERS)
        if wants_batch and not file_bytes:
            target_format = (intent_data.get("target_format") or "").strip().lower()
            if not target_format:
                target_format = _extract_target_from_text(text)
            if not target_format:
                return SkillResult(
                    response_text=(
                        "What format should I convert all files to?\n"
                        "Example: <b>convert all to PDF</b>"
                    )
                )
            if target_format == "jpeg":
                target_format = "jpg"
            pending = await redis.get(batch_key)
            if not pending:
                return SkillResult(
                    response_text=(
                        "No files queued for batch conversion.\n"
                        "Send me files first, then say <b>convert all to PDF</b>."
                    )
                )
            return await self._convert_batch(batch_key, target_format)

        # --- File received with no explicit target format: queue it if batch exists ---
        if file_bytes:
            target_format = (intent_data.get("target_format") or "").strip().lower()
            if not target_format:
                target_format = _extract_target_from_text(text)
            if target_format == "jpeg":
                target_format = "jpg"

            # Single-file conversion: file + target format both present
            if target_format:
                return await self._convert_single(file_bytes, filename, mime_type, target_format)

            # No target format — add to batch queue for later conversion
            if len(file_bytes) > MAX_INPUT_SIZE:
                size_mb = len(file_bytes) / (1024 * 1024)
                return SkillResult(
                    response_text=(f"File is too large ({size_mb:.1f} MB). Maximum: 20 MB.")
                )
            return await self._add_to_batch(
                batch_key, file_bytes, filename or "document", mime_type or ""
            )

        # --- No file attached: ask user to send a file ---
        lang = context.language or "en"
        if lang == "ru":
            no_file = (
                "Отправьте файл вместе с запросом на конвертацию.\n"
                "Пример: прикрепите DOCX и напишите <b>конвертируй в PDF</b>"
            )
        elif lang == "es":
            no_file = (
                "Envie un archivo junto con su solicitud de conversion.\n"
                "Ejemplo: adjunte un DOCX y escriba <b>convertir a PDF</b>"
            )
        else:
            no_file = (
                "Please send a file along with your conversion request.\n"
                "Example: attach a DOCX and write <b>convert to PDF</b>"
            )
        return SkillResult(response_text=no_file)

    # ------------------------------------------------------------------
    # Single-file conversion (original behaviour, extracted to a method)
    # ------------------------------------------------------------------

    async def _convert_single(
        self,
        file_bytes: bytes,
        filename: str | None,
        mime_type: str | None,
        target_format: str,
    ) -> SkillResult:
        """Convert one file and return the result directly."""
        # Detect source format
        source_format = detect_source_format(filename, mime_type)
        if not source_format:
            return SkillResult(
                response_text=(
                    "I couldn't determine the file format. "
                    "Make sure the file has a proper extension."
                )
            )
        if source_format == "jpeg":
            source_format = "jpg"

        # File size check
        if len(file_bytes) > MAX_INPUT_SIZE:
            size_mb = len(file_bytes) / (1024 * 1024)
            return SkillResult(
                response_text=f"File is too large ({size_mb:.1f} MB). Maximum: 20 MB."
            )

        # Same format check
        if source_format == target_format:
            return SkillResult(
                response_text=f"The file is already in <b>{target_format.upper()}</b> format."
            )

        # Supported conversion check
        if not is_supported(source_format, target_format):
            targets = get_supported_targets(source_format)
            if targets:
                target_list = ", ".join(f"<b>{t.upper()}</b>" for t in sorted(targets))
                return SkillResult(
                    response_text=(
                        f"Can't convert <b>{source_format.upper()}</b> to "
                        f"<b>{target_format.upper()}</b>.\n"
                        f"Supported targets: {target_list}"
                    )
                )
            return SkillResult(
                response_text=(
                    f"Format <b>{source_format.upper()}</b> is not supported for conversion."
                )
            )

        # Perform conversion
        src_filename = filename or f"document.{source_format}"
        try:
            output_bytes, output_name = await convert_document(
                file_bytes, source_format, target_format, src_filename
            )
        except ConversionError as e:
            logger.warning("Conversion failed: %s -> %s: %s", source_format, target_format, e)
            return SkillResult(
                response_text=(f"Conversion failed: {e}\nTry a different format or check the file.")
            )
        except Exception:
            logger.exception("Unexpected conversion error")
            return SkillResult(response_text="Something went wrong during conversion. Try again?")

        size_kb = len(output_bytes) / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        return SkillResult(
            response_text=(
                f"Converted <b>{source_format.upper()}</b> → "
                f"<b>{target_format.upper()}</b> ({size_str})"
            ),
            document=output_bytes,
            document_name=output_name,
        )

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    async def _add_to_batch(
        self,
        batch_key: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> SkillResult:
        """Add a file to the batch conversion queue in Redis."""
        pending = await redis.get(batch_key)
        if pending:
            meta = json.loads(pending)
        else:
            meta = {"count": 0, "names": [], "mime_types": [], "files": []}

        if meta["count"] >= MAX_BATCH:
            return SkillResult(
                response_text=(
                    f"Maximum {MAX_BATCH} files reached. "
                    "Say <b>convert all to PDF</b> (or your target format) to convert them."
                )
            )

        meta["count"] += 1
        meta["names"].append(filename)
        meta["mime_types"].append(mime_type)
        meta["files"].append(base64.b64encode(file_bytes).decode())

        await redis.set(batch_key, json.dumps(meta), ex=BATCH_TTL)

        count = meta["count"]
        if count == 1:
            return SkillResult(
                response_text=(
                    f"<b>{filename}</b> added to batch (1 file).\n"
                    "Send more files, then say <b>convert all to PDF</b> "
                    "(or any target format)."
                )
            )
        return SkillResult(
            response_text=(
                f"<b>{filename}</b> added ({count} files total).\n"
                "Send more files or say <b>convert all to PDF</b>."
            )
        )

    async def _convert_batch(self, batch_key: str, target_format: str) -> SkillResult:
        """Convert all queued files, zip the results, and return a single archive."""
        pending = await redis.get(batch_key)
        if not pending:
            return SkillResult(response_text="No files queued. Send me files first.")

        meta = json.loads(pending)
        files_b64: list[str] = meta.get("files", [])
        names: list[str] = meta.get("names", [])
        mime_types: list[str] = meta.get("mime_types", [])

        if not files_b64:
            return SkillResult(response_text="No files in the queue. Send files first.")

        converted: list[tuple[str, bytes]] = []
        errors: list[str] = []

        for i, (b64, name, mime) in enumerate(zip(files_b64, names, mime_types)):
            raw = base64.b64decode(b64)
            source_format = detect_source_format(name, mime)
            if not source_format:
                errors.append(f"{name}: unknown source format")
                continue
            if source_format == "jpeg":
                source_format = "jpg"
            if source_format == target_format:
                errors.append(f"{name}: already {target_format.upper()}")
                continue
            if not is_supported(source_format, target_format):
                errors.append(
                    f"{name}: {source_format.upper()} → {target_format.upper()} not supported"
                )
                continue
            try:
                out_bytes, out_name = await convert_document(
                    raw, source_format, target_format, name
                )
                converted.append((out_name, out_bytes))
            except ConversionError as e:
                logger.warning("Batch conversion failed for %s: %s", name, e)
                errors.append(f"{name}: {e}")
            except Exception:
                logger.exception("Unexpected batch conversion error for %s", name)
                errors.append(f"{name}: unexpected error")

        # Clean up Redis regardless of outcome
        await redis.delete(batch_key)

        if not converted:
            error_lines = "\n".join(f"  • {e}" for e in errors)
            return SkillResult(
                response_text=(f"None of the files could be converted.\n{error_lines}")
            )

        # If only one file converted successfully, return it directly
        if len(converted) == 1:
            out_name, out_bytes = converted[0]
            size_kb = len(out_bytes) / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            summary = f"Converted 1 file to <b>{target_format.upper()}</b> ({size_str})"
            if errors:
                err_lines = "\n".join(f"  • {e}" for e in errors)
                summary += f"\n\nSkipped:\n{err_lines}"
            return SkillResult(
                response_text=summary,
                document=out_bytes,
                document_name=out_name,
            )

        # Multiple files: zip them all
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for out_name, out_bytes in converted:
                zf.writestr(out_name, out_bytes)
        zip_bytes = zip_buffer.getvalue()

        size_kb = len(zip_bytes) / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        summary = (
            f"Converted <b>{len(converted)}</b> file(s) to "
            f"<b>{target_format.upper()}</b> — packed into a ZIP ({size_str})"
        )
        if errors:
            err_lines = "\n".join(f"  • {e}" for e in errors)
            summary += f"\n\nSkipped ({len(errors)}):\n{err_lines}"

        return SkillResult(
            response_text=summary,
            document=zip_bytes,
            document_name=f"converted_{target_format}.zip",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


def _extract_target_from_text(text: str) -> str:
    """Try to extract target format from user message text."""
    text_lower = text.lower()
    m = re.search(
        r"(?:to|в|на|into|как|в формат|save as|сохрани как)\s+\.?(\w{2,5})\b",
        text_lower,
    )
    if m:
        candidate = m.group(1)
        if candidate in KNOWN_FORMATS:
            return candidate
    return ""


skill = ConvertDocumentSkill()
