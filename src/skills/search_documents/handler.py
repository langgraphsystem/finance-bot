"""Search documents skill — full-text search across stored documents."""

import logging
import uuid
from typing import Any

from sqlalchemy import or_, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.document import Document
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


class SearchDocumentsSkill:
    name = "search_documents"
    intents = ["search_documents"]
    model = "claude-sonnet-4-6"

    @observe(name="search_documents")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = intent_data.get("search_query") or message.text or ""
        query = query.strip()
        if not query:
            lang = context.language or "en"
            if lang == "ru":
                text = "Что искать в ваших документах?"
            elif lang == "es":
                text = "Que debo buscar en sus documentos?"
            else:
                text = "What should I search for in your documents?"
            return SkillResult(response_text=text)

        search_pattern = f"%{query}%"

        async with async_session() as session:
            stmt = (
                select(Document)
                .where(Document.family_id == uuid.UUID(context.family_id))
                .where(
                    or_(
                        Document.extracted_text.ilike(search_pattern),
                        Document.title.ilike(search_pattern),
                        Document.file_name.ilike(search_pattern),
                    )
                )
                .order_by(Document.created_at.desc())
                .limit(10)
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

        lang = context.language or "en"
        if not docs:
            if lang == "ru":
                return SkillResult(
                    response_text=f'Документы по запросу "<b>{query}</b>" не найдены.'
                )
            elif lang == "es":
                return SkillResult(
                    response_text=f'No se encontraron documentos para "<b>{query}</b>".'
                )
            return SkillResult(response_text=f'No documents found matching "<b>{query}</b>".')

        if lang == "ru":
            header = f'<b>Найдено {len(docs)} документ(ов) по запросу "{query}"</b>\n'
        elif lang == "es":
            header = f'<b>Se encontraron {len(docs)} documento(s) para "{query}"</b>\n'
        else:
            header = f'<b>Found {len(docs)} document(s) for "{query}"</b>\n'
        lines = [header]
        for doc in docs:
            title = doc.title or doc.file_name or doc.type
            date_str = doc.created_at.strftime("%d.%m.%Y") if doc.created_at else ""
            lines.append(f"\U0001f4c4 <b>{title}</b> — {date_str}")

            # Show a snippet of matching text
            if doc.extracted_text and query.lower() in doc.extracted_text.lower():
                idx = doc.extracted_text.lower().find(query.lower())
                start = max(0, idx - 50)
                end = min(len(doc.extracted_text), idx + len(query) + 50)
                snippet = doc.extracted_text[start:end].replace("\n", " ")
                if start > 0:
                    snippet = "..." + snippet
                if end < len(doc.extracted_text):
                    snippet += "..."
                lines.append(f"  <i>{snippet}</i>")

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Search user's stored documents by content."


skill = SearchDocumentsSkill()
