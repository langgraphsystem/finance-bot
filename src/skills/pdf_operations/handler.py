"""PDF manipulation: split, rotate, encrypt, decrypt, extract pages."""

import asyncio
import base64
import io
import logging
import re
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You perform PDF operations: extract pages, split, rotate, encrypt, decrypt.
Upload a PDF and tell me what to do. Use HTML tags for Telegram."""

SUPPORTED_OPS = {
    "extract_pages": "Extract specific pages into a new PDF",
    "rotate": "Rotate pages by 90, 180, or 270 degrees",
    "encrypt": "Add password protection",
    "decrypt": "Remove password protection",
    "split": "Split into multiple parts",
}

_STRINGS = {
    "en": {
        "no_file": "Upload a <b>PDF</b> file.",
    },
    "ru": {
        "no_file": "Отправьте <b>PDF</b> файл.",
    },
    "es": {
        "no_file": "Suba un archivo <b>PDF</b>.",
    },
}
register_strings("pdf_operations", _STRINGS)


def _parse_page_range(page_str: str, total_pages: int) -> list[int]:
    """Parse page range string like '1-3,5,7-9' into 0-based page indices."""
    pages: list[int] = []
    if not page_str:
        return pages

    for part in page_str.split(","):
        part = part.strip()
        match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if match:
            start = max(1, int(match.group(1)))
            end = min(total_pages, int(match.group(2)))
            pages.extend(range(start - 1, end))
        elif part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < total_pages:
                pages.append(idx)

    return sorted(set(pages))


def _extract_pages(file_bytes: bytes, page_indices: list[int]) -> bytes:
    """Extract specific pages from a PDF."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()
    for idx in page_indices:
        if idx < len(reader.pages):
            writer.add_page(reader.pages[idx])

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _rotate_pages(file_bytes: bytes, degrees: int, page_indices: list[int] | None = None) -> bytes:
    """Rotate pages by given degrees (90, 180, 270)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if page_indices is None or i in page_indices:
            page.rotate(degrees)
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _encrypt_pdf(file_bytes: bytes, password: str) -> bytes:
    """Add password protection to a PDF."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt(password)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _decrypt_pdf(file_bytes: bytes, password: str) -> tuple[bytes, bool]:
    """Remove password protection. Returns (output_bytes, success)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        if not reader.decrypt(password):
            return b"", False

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), True


def _split_pdf(file_bytes: bytes, parts: int) -> list[tuple[bytes, str]]:
    """Split PDF into N roughly equal parts. Returns list of (bytes, name)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)
    pages_per_part = max(1, total // parts)

    results: list[tuple[bytes, str]] = []
    for i in range(parts):
        writer = PdfWriter()
        start = i * pages_per_part
        end = start + pages_per_part if i < parts - 1 else total
        if start >= total:
            break
        for j in range(start, end):
            writer.add_page(reader.pages[j])

        output = io.BytesIO()
        writer.write(output)
        results.append((output.getvalue(), f"part_{i + 1}.pdf"))

    return results


class PdfOperationsSkill:
    name = "pdf_operations"
    intents = ["pdf_operations"]
    model = "claude-sonnet-4-6"

    @observe(name="pdf_operations")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        file_bytes = message.document_bytes
        filename = message.document_file_name or ""

        if not file_bytes:
            lang = context.language or "en"
            return SkillResult(response_text=t_cached(_STRINGS, "no_file", lang, "pdf_operations"))

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = message.document_mime_type or ""
        if ext != "pdf" and "pdf" not in mime:
            return SkillResult(response_text="This skill only works with <b>PDF</b> files.")

        operation = (intent_data.get("pdf_operation") or "").strip().lower()
        pages_str = intent_data.get("pdf_pages") or ""
        password = intent_data.get("pdf_password") or ""

        # Get page count for context
        try:
            from pypdf import PdfReader

            reader = await asyncio.to_thread(lambda: PdfReader(io.BytesIO(file_bytes)))
            total_pages = len(reader.pages)
            is_encrypted = reader.is_encrypted
        except Exception as e:
            logger.exception("Failed to read PDF: %s", e)
            return SkillResult(response_text="Failed to read the PDF. The file may be corrupted.")

        # If no operation specified, show available operations
        if not operation:
            ops_list = "\n".join(f"  <b>{op}</b> -- {desc}" for op, desc in SUPPORTED_OPS.items())
            return SkillResult(
                response_text=(
                    f"<b>PDF</b>: {filename} ({total_pages} pages)\n\n"
                    f"Available operations:\n{ops_list}\n\n"
                    "Example: <code>extract pages 1-3</code>"
                )
            )

        # Route to operation
        if operation == "extract_pages":
            return await self._extract_pages(file_bytes, filename, pages_str, total_pages)
        elif operation == "rotate":
            degrees = intent_data.get("pdf_degrees") or 90
            if isinstance(degrees, str):
                degrees = int(degrees) if degrees.isdigit() else 90
            return await self._rotate(file_bytes, filename, degrees, pages_str, total_pages)
        elif operation == "encrypt":
            return await self._encrypt(file_bytes, filename, password)
        elif operation == "decrypt":
            return await self._decrypt(file_bytes, filename, password, is_encrypted)
        elif operation == "split":
            parts = intent_data.get("pdf_parts") or 2
            if isinstance(parts, str):
                parts = int(parts) if parts.isdigit() else 2
            return await self._split(file_bytes, filename, parts, total_pages)
        else:
            return SkillResult(
                response_text=(
                    f"Unknown operation: <b>{operation}</b>.\n"
                    f"Supported: {', '.join(f'<b>{op}</b>' for op in SUPPORTED_OPS)}"
                )
            )

    async def _extract_pages(
        self,
        file_bytes: bytes,
        filename: str,
        pages_str: str,
        total_pages: int,
    ) -> SkillResult:
        if not pages_str:
            return SkillResult(
                response_text=(
                    f"Which pages to extract? (1-{total_pages})\nExample: <code>1-3,5,7</code>"
                )
            )

        page_indices = _parse_page_range(pages_str, total_pages)
        if not page_indices:
            return SkillResult(
                response_text=f"Invalid page range. This PDF has {total_pages} pages."
            )

        try:
            output = await asyncio.to_thread(_extract_pages, file_bytes, page_indices)
        except Exception as e:
            logger.exception("Page extraction failed: %s", e)
            return SkillResult(response_text="Failed to extract pages.")

        display_pages = _format_page_list(page_indices)
        output_name = filename.replace(".pdf", f"_pages_{pages_str}.pdf")
        return SkillResult(
            response_text=(f"<b>Extracted {len(page_indices)} page(s)</b>: {display_pages}"),
            document=output,
            document_name=output_name,
        )

    async def _rotate(
        self,
        file_bytes: bytes,
        filename: str,
        degrees: int,
        pages_str: str,
        total_pages: int,
    ) -> SkillResult:
        if degrees not in (90, 180, 270):
            return SkillResult(
                response_text="Rotation must be <b>90</b>, <b>180</b>, or <b>270</b> degrees."
            )

        page_indices = _parse_page_range(pages_str, total_pages) if pages_str else None
        scope = f"pages {_format_page_list(page_indices)}" if page_indices else "all pages"

        try:
            output = await asyncio.to_thread(_rotate_pages, file_bytes, degrees, page_indices)
        except Exception as e:
            logger.exception("Rotation failed: %s", e)
            return SkillResult(response_text="Failed to rotate pages.")

        output_name = filename.replace(".pdf", f"_rotated_{degrees}.pdf")
        return SkillResult(
            response_text=f"<b>Rotated {scope}</b> by {degrees} degrees.",
            document=output,
            document_name=output_name,
        )

    async def _encrypt(self, file_bytes: bytes, filename: str, password: str) -> SkillResult:
        if not password:
            return SkillResult(
                response_text=(
                    "Provide a password to protect this PDF.\n"
                    "Example: <code>encrypt with password mySecret123</code>"
                )
            )

        try:
            output = await asyncio.to_thread(_encrypt_pdf, file_bytes, password)
        except Exception as e:
            logger.exception("Encryption failed: %s", e)
            return SkillResult(response_text="Failed to encrypt the PDF.")

        output_name = filename.replace(".pdf", "_encrypted.pdf")
        return SkillResult(
            response_text="<b>PDF encrypted</b> with your password.",
            document=output,
            document_name=output_name,
        )

    async def _decrypt(
        self,
        file_bytes: bytes,
        filename: str,
        password: str,
        is_encrypted: bool,
    ) -> SkillResult:
        if not is_encrypted:
            return SkillResult(response_text="This PDF is not encrypted.")

        if not password:
            return SkillResult(
                response_text=(
                    "Provide the password to decrypt this PDF.\n"
                    "Example: <code>decrypt with password mySecret123</code>"
                )
            )

        try:
            output, success = await asyncio.to_thread(_decrypt_pdf, file_bytes, password)
        except Exception as e:
            logger.exception("Decryption failed: %s", e)
            return SkillResult(response_text="Failed to decrypt the PDF.")

        if not success:
            return SkillResult(response_text="Wrong password. Please try again.")

        output_name = filename.replace(".pdf", "_decrypted.pdf")
        return SkillResult(
            response_text="<b>PDF decrypted</b> successfully.",
            document=output,
            document_name=output_name,
        )

    async def _split(
        self,
        file_bytes: bytes,
        filename: str,
        parts: int,
        total_pages: int,
    ) -> SkillResult:
        if parts < 2:
            return SkillResult(response_text="Need at least 2 parts to split.")
        if parts > total_pages:
            return SkillResult(
                response_text=(
                    f"Can't split {total_pages} pages into {parts} parts. "
                    f"Maximum parts: {total_pages}."
                )
            )

        try:
            results = await asyncio.to_thread(_split_pdf, file_bytes, parts)
        except Exception as e:
            logger.exception("Split failed: %s", e)
            return SkillResult(response_text="Failed to split the PDF.")

        # Return the first part as a document, list all parts info
        if not results:
            return SkillResult(response_text="Split produced no output.")

        # For Telegram, we can only send one document at a time.
        # Return the first part and mention the rest.
        first_bytes, first_name = results[0]
        base = filename.replace(".pdf", "")

        if len(results) == 1:
            return SkillResult(
                response_text="<b>Split into 1 part</b> (PDF too small to split further).",
                document=first_bytes,
                document_name=f"{base}_part1.pdf",
            )

        # Store remaining parts in Redis so user can request them by number
        info_lines = []
        for i, (part_bytes, _) in enumerate(results):
            from pypdf import PdfReader

            pr = PdfReader(io.BytesIO(part_bytes))
            info_lines.append(f"  Part {i + 1}: {len(pr.pages)} pages")

            if i > 0:
                key = f"pdf_split:{base}:part{i + 1}"
                await redis.set(key, base64.b64encode(part_bytes).decode(), ex=3600)

        return SkillResult(
            response_text=(
                f"<b>Split into {len(results)} parts</b>\n"
                + "\n".join(info_lines)
                + "\n\n<i>Sending part 1. Ask for other parts by number.</i>"
            ),
            document=first_bytes,
            document_name=f"{base}_part1.pdf",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


def _format_page_list(indices: list[int] | None) -> str:
    """Format 0-based page indices as human-readable 1-based list."""
    if not indices:
        return ""
    return ", ".join(str(i + 1) for i in indices)


skill = PdfOperationsSkill()
