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
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You merge multiple PDF files into a single document.
Send PDF files one by one, then say 'done' or 'merge' to combine them.
Be concise. Use HTML tags for Telegram."""

PENDING_MERGE_TTL = 1800  # 30 minutes
MERGE_KEY_PREFIX = "pdf_merge"
MAX_FILES = 20


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
            return await self._finish_merge(merge_key)

        # User sent a file — add it to the merge queue
        if file_bytes:
            if ext != "pdf" and "pdf" not in mime:
                return SkillResult(
                    response_text="Only <b>PDF</b> files can be merged. "
                    f"You sent a <b>{ext.upper() or 'unknown'}</b> file."
                )

            return await self._add_to_queue(merge_key, file_bytes, filename)

        # No file, not finishing — check if there's a pending merge
        pending = await redis.get(merge_key)
        if pending:
            meta = json.loads(pending)
            count = meta.get("count", 0)
            names = meta.get("names", [])
            name_list = "\n".join(f"  {i + 1}. {n}" for i, n in enumerate(names))
            return SkillResult(
                response_text=(
                    f"<b>Merge in progress</b> ({count} file(s) queued)\n"
                    f"{name_list}\n\n"
                    "Send more PDFs or say <b>done</b> to merge them."
                )
            )

        return SkillResult(
            response_text=(
                "Send me the <b>PDF files</b> you want to merge, one by one.\n"
                "When you're done, say <b>done</b> and I'll combine them."
            )
        )

    async def _add_to_queue(self, merge_key: str, file_bytes: bytes, filename: str) -> SkillResult:
        """Add a PDF to the merge queue in Redis."""
        import base64

        # Load existing queue
        pending = await redis.get(merge_key)
        if pending:
            meta = json.loads(pending)
        else:
            meta = {"count": 0, "names": [], "files": []}

        if meta["count"] >= MAX_FILES:
            return SkillResult(
                response_text=f"Maximum {MAX_FILES} files reached. "
                "Say <b>done</b> to merge them now."
            )

        meta["count"] += 1
        meta["names"].append(filename or f"file_{meta['count']}.pdf")
        meta["files"].append(base64.b64encode(file_bytes).decode())

        await redis.set(merge_key, json.dumps(meta), ex=PENDING_MERGE_TTL)

        count = meta["count"]
        if count == 1:
            return SkillResult(
                response_text=(
                    f"<b>{filename or 'PDF'}</b> added (1 file).\n"
                    "Send the next PDF, or say <b>done</b> to merge."
                )
            )
        return SkillResult(
            response_text=(
                f"<b>{filename or 'PDF'}</b> added ({count} files total).\n"
                "Send more PDFs or say <b>done</b> to merge."
            )
        )

    async def _finish_merge(self, merge_key: str) -> SkillResult:
        """Merge all queued PDFs and return the result."""
        import base64

        pending = await redis.get(merge_key)
        if not pending:
            return SkillResult(response_text="No PDFs queued. Send me PDF files first.")

        meta = json.loads(pending)
        files_b64 = meta.get("files", [])
        names = meta.get("names", [])

        if len(files_b64) < 2:
            return SkillResult(
                response_text="Need at least <b>2 PDFs</b> to merge. Send another file."
            )

        pdf_list = [base64.b64decode(f) for f in files_b64]

        try:
            merged_bytes = await asyncio.to_thread(_merge_pdfs, pdf_list)
        except Exception as e:
            logger.exception("PDF merge failed: %s", e)
            return SkillResult(
                response_text="Failed to merge the PDFs. One of the files may be corrupted."
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
            response_text=(
                f"<b>Merged {len(pdf_list)} PDFs</b>{total_pages_info} ({size_str})\n{name_list}"
            ),
            document=merged_bytes,
            document_name="merged.pdf",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SYSTEM_PROMPT


skill = MergeDocumentsSkill()
