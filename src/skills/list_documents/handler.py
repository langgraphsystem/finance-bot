"""List documents skill — show user's stored documents."""

import logging
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.document import Document
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DOC_TYPE_LABELS = {
    "receipt": "Чек",
    "invoice": "Инвойс",
    "rate_confirmation": "Rate Confirmation",
    "fuel_receipt": "Заправочный чек",
    "contract": "Контракт",
    "form": "Форма",
    "report": "Отчёт",
    "template": "Шаблон",
    "spreadsheet": "Таблица",
    "presentation": "Презентация",
    "other": "Документ",
}


class ListDocumentsSkill:
    name = "list_documents"
    intents = ["list_documents"]
    model = "claude-sonnet-4-6"

    @observe(name="list_documents")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        doc_type = intent_data.get("document_type")
        limit = 20

        async with async_session() as session:
            stmt = (
                select(Document)
                .where(Document.family_id == context.family_id)
                .order_by(Document.created_at.desc())
                .limit(limit)
            )
            if doc_type:
                stmt = stmt.where(Document.type == doc_type)

            result = await session.execute(stmt)
            docs = result.scalars().all()

        if not docs:
            return SkillResult(response_text="No documents found.")

        lines = [f"<b>Documents ({len(docs)})</b>\n"]
        for doc in docs:
            icon = _type_icon(doc.type)
            label = DOC_TYPE_LABELS.get(doc.type, doc.type)
            title = doc.title or doc.file_name or label
            date_str = doc.created_at.strftime("%d.%m.%Y") if doc.created_at else ""
            size_str = _format_size(doc.file_size_bytes) if doc.file_size_bytes else ""
            parts = [f"{icon} <b>{title}</b>"]
            if date_str:
                parts.append(date_str)
            if size_str:
                parts.append(size_str)
            lines.append(" — ".join(parts))

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return "List user's stored documents. Be concise."


def _type_icon(doc_type: str) -> str:
    icons = {
        "receipt": "\U0001f9fe",
        "invoice": "\U0001f4c4",
        "rate_confirmation": "\U0001f69a",
        "fuel_receipt": "\u26fd",
        "contract": "\U0001f4dc",
        "form": "\U0001f4cb",
        "report": "\U0001f4ca",
        "template": "\U0001f4c2",
        "spreadsheet": "\U0001f4ca",
        "presentation": "\U0001f4fd",
        "other": "\U0001f4c4",
    }
    return icons.get(doc_type, "\U0001f4c4")


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


skill = ListDocumentsSkill()
