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
Upload a PDF and tell me what to do. Use HTML tags for Telegram.
Respond in: {language}."""

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
        "not_pdf": "This skill only works with <b>PDF</b> files.",
        "read_failed": "Failed to read the PDF. The file may be corrupted.",
        "unknown_op": "Unknown operation: <b>{op}</b>.\nSupported: {ops}",
        "ask_pages": "Which pages to extract? (1-{total})\nExample: <code>1-3,5,7</code>",
        "invalid_range": "Invalid page range. This PDF has {total} pages.",
        "extract_failed": "Failed to extract pages.",
        "extracted_ok": "<b>Extracted {count} page(s)</b>: {pages}",
        "bad_degrees": "Rotation must be <b>90</b>, <b>180</b>, or <b>270</b> degrees.",
        "rotate_failed": "Failed to rotate pages.",
        "rotated_ok": "<b>Rotated {scope}</b> by {degrees} degrees.",
        "ask_password": (
            "Provide a password to protect this PDF.\n"
            "Example: <code>encrypt with password mySecret123</code>"
        ),
        "encrypt_failed": "Failed to encrypt the PDF.",
        "encrypted_ok": "<b>PDF encrypted</b> with your password.",
        "not_encrypted": "This PDF is not encrypted.",
        "ask_decrypt_pw": (
            "Provide the password to decrypt this PDF.\n"
            "Example: <code>decrypt with password mySecret123</code>"
        ),
        "decrypt_failed": "Failed to decrypt the PDF.",
        "wrong_password": "Wrong password. Please try again.",
        "decrypted_ok": "<b>PDF decrypted</b> successfully.",
        "split_min": "Need at least 2 parts to split.",
        "split_max": (
            "Can't split {total} pages into {parts} parts. Maximum parts: {total}."
        ),
        "split_failed": "Failed to split the PDF.",
        "split_empty": "Split produced no output.",
        "split_one": "<b>Split into 1 part</b> (PDF too small to split further).",
        "split_ok": "<b>Split into {count} parts</b>",
        "ops_header": (
            "<b>PDF</b>: {filename} ({pages} pages)\n\n"
            "Available operations:\n{ops}\n\n"
            "Example: <code>extract pages 1-3</code>"
        ),
    },
    "ru": {
        "no_file": "Отправьте <b>PDF</b> файл.",
        "not_pdf": "Этот навык работает только с <b>PDF</b> файлами.",
        "read_failed": "Не удалось прочитать PDF. Файл может быть повреждён.",
        "unknown_op": "Неизвестная операция: <b>{op}</b>.\nДоступно: {ops}",
        "ask_pages": "Какие страницы извлечь? (1-{total})\nПример: <code>1-3,5,7</code>",
        "invalid_range": "Неверный диапазон. В этом PDF {total} страниц.",
        "extract_failed": "Не удалось извлечь страницы.",
        "extracted_ok": "<b>Извлечено {count} страниц(ы)</b>: {pages}",
        "bad_degrees": "Поворот должен быть <b>90</b>, <b>180</b> или <b>270</b> градусов.",
        "rotate_failed": "Не удалось повернуть страницы.",
        "rotated_ok": "<b>Повёрнуто {scope}</b> на {degrees} градусов.",
        "ask_password": (
            "Укажите пароль для защиты PDF.\n"
            "Пример: <code>зашифруй паролем mySecret123</code>"
        ),
        "encrypt_failed": "Не удалось зашифровать PDF.",
        "encrypted_ok": "<b>PDF зашифрован</b> вашим паролем.",
        "not_encrypted": "Этот PDF не зашифрован.",
        "ask_decrypt_pw": (
            "Укажите пароль для расшифровки PDF.\n"
            "Пример: <code>расшифруй паролем mySecret123</code>"
        ),
        "decrypt_failed": "Не удалось расшифровать PDF.",
        "wrong_password": "Неверный пароль. Попробуйте снова.",
        "decrypted_ok": "<b>PDF расшифрован</b> успешно.",
        "split_min": "Для разделения нужно минимум 2 части.",
        "split_max": (
            "Невозможно разделить {total} страниц на {parts} частей. Максимум: {total}."
        ),
        "split_failed": "Не удалось разделить PDF.",
        "split_empty": "Разделение не дало результата.",
        "split_one": "<b>Разделён на 1 часть</b> (PDF слишком маленький).",
        "split_ok": "<b>Разделён на {count} частей</b>",
        "ops_header": (
            "<b>PDF</b>: {filename} ({pages} стр.)\n\n"
            "Доступные операции:\n{ops}\n\n"
            "Пример: <code>извлечь страницы 1-3</code>"
        ),
    },
    "es": {
        "no_file": "Suba un archivo <b>PDF</b>.",
        "not_pdf": "Esta herramienta solo funciona con archivos <b>PDF</b>.",
        "read_failed": "No se pudo leer el PDF. El archivo puede estar danado.",
        "unknown_op": "Operacion desconocida: <b>{op}</b>.\nDisponibles: {ops}",
        "ask_pages": "Que paginas extraer? (1-{total})\nEjemplo: <code>1-3,5,7</code>",
        "invalid_range": "Rango invalido. Este PDF tiene {total} paginas.",
        "extract_failed": "No se pudieron extraer las paginas.",
        "extracted_ok": "<b>{count} pagina(s) extraidas</b>: {pages}",
        "bad_degrees": "La rotacion debe ser <b>90</b>, <b>180</b> o <b>270</b> grados.",
        "rotate_failed": "No se pudieron rotar las paginas.",
        "rotated_ok": "<b>Rotado {scope}</b> {degrees} grados.",
        "ask_password": (
            "Proporcione una contrasena para proteger el PDF.\n"
            "Ejemplo: <code>cifrar con contrasena mySecret123</code>"
        ),
        "encrypt_failed": "No se pudo cifrar el PDF.",
        "encrypted_ok": "<b>PDF cifrado</b> con su contrasena.",
        "not_encrypted": "Este PDF no esta cifrado.",
        "ask_decrypt_pw": (
            "Proporcione la contrasena para descifrar el PDF.\n"
            "Ejemplo: <code>descifrar con contrasena mySecret123</code>"
        ),
        "decrypt_failed": "No se pudo descifrar el PDF.",
        "wrong_password": "Contrasena incorrecta. Intente de nuevo.",
        "decrypted_ok": "<b>PDF descifrado</b> exitosamente.",
        "split_min": "Se necesitan al menos 2 partes para dividir.",
        "split_max": (
            "No se pueden dividir {total} paginas en {parts} partes. Maximo: {total}."
        ),
        "split_failed": "No se pudo dividir el PDF.",
        "split_empty": "La division no produjo resultados.",
        "split_one": "<b>Dividido en 1 parte</b> (PDF demasiado pequeno).",
        "split_ok": "<b>Dividido en {count} partes</b>",
        "ops_header": (
            "<b>PDF</b>: {filename} ({pages} pags.)\n\n"
            "Operaciones disponibles:\n{ops}\n\n"
            "Ejemplo: <code>extraer paginas 1-3</code>"
        ),
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
        lang = context.language or "en"
        _ns = "pdf_operations"
        file_bytes = message.document_bytes
        filename = message.document_file_name or ""

        if not file_bytes:
            return SkillResult(response_text=t_cached(_STRINGS, "no_file", lang, _ns))

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = message.document_mime_type or ""
        if ext != "pdf" and "pdf" not in mime:
            return SkillResult(response_text=t_cached(_STRINGS, "not_pdf", lang, _ns))

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
            return SkillResult(response_text=t_cached(_STRINGS, "read_failed", lang, _ns))

        # If no operation specified, show available operations
        if not operation:
            ops_list = "\n".join(f"  <b>{op}</b> -- {desc}" for op, desc in SUPPORTED_OPS.items())
            return SkillResult(
                response_text=t_cached(_STRINGS, "ops_header", lang, _ns).format(
                    filename=filename, pages=total_pages, ops=ops_list
                )
            )

        # Route to operation
        if operation == "extract_pages":
            return await self._extract_pages(file_bytes, filename, pages_str, total_pages, lang)
        elif operation == "rotate":
            degrees = intent_data.get("pdf_degrees") or 90
            if isinstance(degrees, str):
                degrees = int(degrees) if degrees.isdigit() else 90
            return await self._rotate(file_bytes, filename, degrees, pages_str, total_pages, lang)
        elif operation == "encrypt":
            return await self._encrypt(file_bytes, filename, password, lang)
        elif operation == "decrypt":
            return await self._decrypt(file_bytes, filename, password, is_encrypted, lang)
        elif operation == "split":
            parts = intent_data.get("pdf_parts") or 2
            if isinstance(parts, str):
                parts = int(parts) if parts.isdigit() else 2
            return await self._split(file_bytes, filename, parts, total_pages, lang)
        else:
            ops_str = ", ".join(f"<b>{op}</b>" for op in SUPPORTED_OPS)
            return SkillResult(
                response_text=t_cached(_STRINGS, "unknown_op", lang, _ns).format(
                    op=operation, ops=ops_str
                )
            )

    async def _extract_pages(
        self,
        file_bytes: bytes,
        filename: str,
        pages_str: str,
        total_pages: int,
        lang: str = "en",
    ) -> SkillResult:
        _ns = "pdf_operations"
        if not pages_str:
            return SkillResult(
                response_text=t_cached(_STRINGS, "ask_pages", lang, _ns).format(total=total_pages)
            )

        page_indices = _parse_page_range(pages_str, total_pages)
        if not page_indices:
            return SkillResult(
                response_text=t_cached(_STRINGS, "invalid_range", lang, _ns).format(
                    total=total_pages
                )
            )

        try:
            output = await asyncio.to_thread(_extract_pages, file_bytes, page_indices)
        except Exception as e:
            logger.exception("Page extraction failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "extract_failed", lang, _ns)
            )

        display_pages = _format_page_list(page_indices)
        output_name = filename.replace(".pdf", f"_pages_{pages_str}.pdf")
        return SkillResult(
            response_text=t_cached(_STRINGS, "extracted_ok", lang, _ns).format(
                count=len(page_indices), pages=display_pages
            ),
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
        lang: str = "en",
    ) -> SkillResult:
        _ns = "pdf_operations"
        if degrees not in (90, 180, 270):
            return SkillResult(
                response_text=t_cached(_STRINGS, "bad_degrees", lang, _ns)
            )

        page_indices = _parse_page_range(pages_str, total_pages) if pages_str else None
        scope = f"pages {_format_page_list(page_indices)}" if page_indices else "all pages"

        try:
            output = await asyncio.to_thread(_rotate_pages, file_bytes, degrees, page_indices)
        except Exception as e:
            logger.exception("Rotation failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "rotate_failed", lang, _ns)
            )

        output_name = filename.replace(".pdf", f"_rotated_{degrees}.pdf")
        return SkillResult(
            response_text=t_cached(_STRINGS, "rotated_ok", lang, _ns).format(
                scope=scope, degrees=degrees
            ),
            document=output,
            document_name=output_name,
        )

    async def _encrypt(
        self, file_bytes: bytes, filename: str, password: str, lang: str = "en"
    ) -> SkillResult:
        _ns = "pdf_operations"
        if not password:
            return SkillResult(
                response_text=t_cached(_STRINGS, "ask_password", lang, _ns)
            )

        try:
            output = await asyncio.to_thread(_encrypt_pdf, file_bytes, password)
        except Exception as e:
            logger.exception("Encryption failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "encrypt_failed", lang, _ns)
            )

        output_name = filename.replace(".pdf", "_encrypted.pdf")
        return SkillResult(
            response_text=t_cached(_STRINGS, "encrypted_ok", lang, _ns),
            document=output,
            document_name=output_name,
        )

    async def _decrypt(
        self,
        file_bytes: bytes,
        filename: str,
        password: str,
        is_encrypted: bool,
        lang: str = "en",
    ) -> SkillResult:
        _ns = "pdf_operations"
        if not is_encrypted:
            return SkillResult(
                response_text=t_cached(_STRINGS, "not_encrypted", lang, _ns)
            )

        if not password:
            return SkillResult(
                response_text=t_cached(_STRINGS, "ask_decrypt_pw", lang, _ns)
            )

        try:
            output, success = await asyncio.to_thread(_decrypt_pdf, file_bytes, password)
        except Exception as e:
            logger.exception("Decryption failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "decrypt_failed", lang, _ns)
            )

        if not success:
            return SkillResult(
                response_text=t_cached(_STRINGS, "wrong_password", lang, _ns)
            )

        output_name = filename.replace(".pdf", "_decrypted.pdf")
        return SkillResult(
            response_text=t_cached(_STRINGS, "decrypted_ok", lang, _ns),
            document=output,
            document_name=output_name,
        )

    async def _split(
        self,
        file_bytes: bytes,
        filename: str,
        parts: int,
        total_pages: int,
        lang: str = "en",
    ) -> SkillResult:
        _ns = "pdf_operations"
        if parts < 2:
            return SkillResult(
                response_text=t_cached(_STRINGS, "split_min", lang, _ns)
            )
        if parts > total_pages:
            return SkillResult(
                response_text=t_cached(_STRINGS, "split_max", lang, _ns).format(
                    total=total_pages, parts=parts
                )
            )

        try:
            results = await asyncio.to_thread(_split_pdf, file_bytes, parts)
        except Exception as e:
            logger.exception("Split failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "split_failed", lang, _ns)
            )

        # Return the first part as a document, list all parts info
        if not results:
            return SkillResult(
                response_text=t_cached(_STRINGS, "split_empty", lang, _ns)
            )

        # For Telegram, we can only send one document at a time.
        # Return the first part and mention the rest.
        first_bytes, first_name = results[0]
        base = filename.replace(".pdf", "")

        if len(results) == 1:
            return SkillResult(
                response_text=t_cached(_STRINGS, "split_one", lang, _ns),
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

        header = t_cached(_STRINGS, "split_ok", lang, _ns).format(count=len(results))
        return SkillResult(
            response_text=(
                f"{header}\n"
                + "\n".join(info_lines)
                + "\n\n<i>Sending part 1. Ask for other parts by number.</i>"
            ),
            document=first_bytes,
            document_name=f"{base}_part1.pdf",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT.format(language=context.language or "en")


def _format_page_list(indices: list[int] | None) -> str:
    """Format 0-based page indices as human-readable 1-based list."""
    if not indices:
        return ""
    return ", ".join(str(i + 1) for i in indices)


skill = PdfOperationsSkill()
