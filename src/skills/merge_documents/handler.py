"""Merge multiple PDF files into one."""

import asyncio
import io
import json
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You merge multiple PDF files into a single document.
Send PDF files one by one, then say 'done' or 'merge' to combine them.
Be concise. Use HTML tags for Telegram.
Respond in: {language}."""

PENDING_MERGE_TTL = 1800  # 30 minutes
MERGE_KEY_PREFIX = "pdf_merge"
MAX_FILES = 20

_STRINGS = {
    "en": {
        "send_pdfs": (
            "Send me the <b>PDF files</b> you want to merge, one by one.\n"
            "When you're done, say <b>done</b> and I'll combine them."
        ),
        "not_pdf": "Only <b>PDF</b> files can be merged. You sent a <b>{format}</b> file.",
        "merge_in_progress": (
            "<b>Merge in progress</b> ({count} file(s) queued)\n{names}\n\n"
            "Send more PDFs or say <b>done</b> to merge them."
        ),
        "max_files": "Maximum {max} files reached. Say <b>done</b> to merge them now.",
        "queue_first": (
            "<b>{name}</b> added (1 file).\n"
            "Send the next PDF, or say <b>done</b> to merge."
        ),
        "queue_added": (
            "<b>{name}</b> added ({count} files total).\n"
            "Send more PDFs or say <b>done</b> to merge."
        ),
        "queue_empty": "No PDFs queued. Send me PDF files first.",
        "need_two": "Need at least <b>2 PDFs</b> to merge. Send another file.",
        "merge_failed": "Failed to merge the PDFs. One of the files may be corrupted.",
        "merged_ok": "<b>Merged {count} PDFs</b>{pages} ({size})\n{names}",
    },
    "ru": {
        "send_pdfs": (
            "Отправьте <b>PDF файлы</b> для объединения, по одному.\n"
            "Когда закончите, скажите <b>done</b> и я объединю их."
        ),
        "not_pdf": "Можно объединять только <b>PDF</b> файлы. Вы отправили <b>{format}</b>.",
        "merge_in_progress": (
            "<b>Объединение</b> ({count} файл(ов) в очереди)\n{names}\n\n"
            "Отправьте ещё PDF или скажите <b>done</b>."
        ),
        "max_files": "Достигнут лимит в {max} файлов. Скажите <b>done</b> для объединения.",
        "queue_first": (
            "<b>{name}</b> добавлен (1 файл).\n"
            "Отправьте следующий PDF или скажите <b>done</b>."
        ),
        "queue_added": (
            "<b>{name}</b> добавлен ({count} файлов).\n"
            "Отправьте ещё или скажите <b>done</b>."
        ),
        "queue_empty": "Нет PDF в очереди. Сначала отправьте файлы.",
        "need_two": "Нужно минимум <b>2 PDF</b> для объединения. Отправьте ещё файл.",
        "merge_failed": "Не удалось объединить PDF. Один из файлов может быть повреждён.",
        "merged_ok": "<b>Объединено {count} PDF</b>{pages} ({size})\n{names}",
    },
    "es": {
        "send_pdfs": (
            "Envieme los <b>archivos PDF</b> que desea combinar, uno por uno.\n"
            "Cuando termine, diga <b>done</b> y los combinare."
        ),
        "not_pdf": "Solo se pueden combinar archivos <b>PDF</b>. Envio un archivo <b>{format}</b>.",
        "merge_in_progress": (
            "<b>Combinacion en curso</b> ({count} archivo(s) en cola)\n{names}\n\n"
            "Envie mas PDFs o diga <b>done</b>."
        ),
        "max_files": "Limite de {max} archivos alcanzado. Diga <b>done</b> para combinarlos.",
        "queue_first": (
            "<b>{name}</b> agregado (1 archivo).\n"
            "Envie el siguiente PDF o diga <b>done</b>."
        ),
        "queue_added": (
            "<b>{name}</b> agregado ({count} archivos).\n"
            "Envie mas o diga <b>done</b>."
        ),
        "queue_empty": "No hay PDFs en cola. Envie archivos primero.",
        "need_two": "Se necesitan al menos <b>2 PDFs</b> para combinar. Envie otro archivo.",
        "merge_failed": (
            "No se pudieron combinar los PDFs. Uno de los archivos puede estar danado."
        ),
        "merged_ok": "<b>{count} PDFs combinados</b>{pages} ({size})\n{names}",
    },
}
register_strings("merge_documents", _STRINGS)


def _merge_pdfs(pdf_list: list[bytes]) -> bytes:
    """Merge multiple PDF byte arrays into one."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf_bytes in pdf_list:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class MergeDocumentsSkill:
    name = "merge_documents"
    intents = ["merge_documents"]
    model = "claude-sonnet-4-6"

    @observe(name="merge_documents")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        _ns = "merge_documents"
        merge_key = f"{MERGE_KEY_PREFIX}:{context.user_id}"
        text = (message.text or "").strip().lower()
        file_bytes = message.document_bytes
        filename = message.document_file_name or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = message.document_mime_type or ""

        # Check if user wants to finish merging
        finish_keywords = ("done", "merge", "finish", "combine", "ready", "go")
        wants_finish = any(kw in text for kw in finish_keywords) and not file_bytes

        if wants_finish:
            return await self._finish_merge(merge_key, lang)

        # User sent a file — add it to the merge queue
        if file_bytes:
            if ext != "pdf" and "pdf" not in mime:
                return SkillResult(
                    response_text=t_cached(_STRINGS, "not_pdf", lang, _ns).format(
                        format=ext.upper() or "unknown"
                    )
                )

            return await self._add_to_queue(merge_key, file_bytes, filename, lang)

        # No file, not finishing — check if there's a pending merge
        pending = await redis.get(merge_key)
        if pending:
            meta = json.loads(pending)
            count = meta.get("count", 0)
            names = meta.get("names", [])
            name_list = "\n".join(f"  {i + 1}. {n}" for i, n in enumerate(names))
            return SkillResult(
                response_text=t_cached(_STRINGS, "merge_in_progress", lang, _ns).format(
                    count=count, names=name_list
                )
            )

        return SkillResult(response_text=t_cached(_STRINGS, "send_pdfs", lang, _ns))

    async def _add_to_queue(
        self, merge_key: str, file_bytes: bytes, filename: str, lang: str = "en"
    ) -> SkillResult:
        """Add a PDF to the merge queue in Redis."""
        import base64

        _ns = "merge_documents"

        # Load existing queue
        pending = await redis.get(merge_key)
        if pending:
            meta = json.loads(pending)
        else:
            meta = {"count": 0, "names": [], "files": []}

        if meta["count"] >= MAX_FILES:
            return SkillResult(
                response_text=t_cached(_STRINGS, "max_files", lang, _ns).format(max=MAX_FILES)
            )

        meta["count"] += 1
        meta["names"].append(filename or f"file_{meta['count']}.pdf")
        meta["files"].append(base64.b64encode(file_bytes).decode())

        await redis.set(merge_key, json.dumps(meta), ex=PENDING_MERGE_TTL)

        count = meta["count"]
        name = filename or "PDF"
        if count == 1:
            return SkillResult(
                response_text=t_cached(_STRINGS, "queue_first", lang, _ns).format(name=name)
            )
        return SkillResult(
            response_text=t_cached(_STRINGS, "queue_added", lang, _ns).format(
                name=name, count=count
            )
        )

    async def _finish_merge(self, merge_key: str, lang: str = "en") -> SkillResult:
        """Merge all queued PDFs and return the result."""
        import base64

        _ns = "merge_documents"
        pending = await redis.get(merge_key)
        if not pending:
            return SkillResult(
                response_text=t_cached(_STRINGS, "queue_empty", lang, _ns)
            )

        meta = json.loads(pending)
        files_b64 = meta.get("files", [])
        names = meta.get("names", [])

        if len(files_b64) < 2:
            return SkillResult(
                response_text=t_cached(_STRINGS, "need_two", lang, _ns)
            )

        pdf_list = [base64.b64decode(f) for f in files_b64]

        try:
            merged_bytes = await asyncio.to_thread(_merge_pdfs, pdf_list)
        except Exception as e:
            logger.exception("PDF merge failed: %s", e)
            return SkillResult(
                response_text=t_cached(_STRINGS, "merge_failed", lang, _ns)
            )

        # Clean up Redis
        await redis.delete(merge_key)

        total_pages_info = ""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(merged_bytes))
            total_pages_info = f" ({len(reader.pages)} pages)"
        except Exception:
            pass

        size_kb = len(merged_bytes) / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"

        name_list = "\n".join(f"  {i + 1}. {n}" for i, n in enumerate(names))
        return SkillResult(
            response_text=t_cached(_STRINGS, "merged_ok", lang, _ns).format(
                count=len(pdf_list), pages=total_pages_info, size=size_str, names=name_list
            ),
            document=merged_bytes,
            document_name="merged.pdf",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT.format(language=context.language or "en")


skill = MergeDocumentsSkill()
