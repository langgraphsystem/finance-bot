"""Search documents skill — hybrid search (pg_trgm + pgvector RRF)."""

import logging
import uuid
from typing import Any

from sqlalchemy import or_, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.document import Document
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "empty_query": "What should I search for in your documents?",
        "not_found": 'No documents found matching "<b>{query}</b>".',
        "header": '<b>Found {count} document(s) for "{query}"</b>\n',
    },
    "ru": {
        "empty_query": "Что искать в ваших документах?",
        "not_found": 'Документы по запросу "<b>{query}</b>" не найдены.',
        "header": '<b>Найдено {count} документ(ов) по запросу "{query}"</b>\n',
    },
    "es": {
        "empty_query": "Que debo buscar en sus documentos?",
        "not_found": 'No se encontraron documentos para "<b>{query}</b>".',
        "header": '<b>Se encontraron {count} documento(s) para "{query}"</b>\n',
    },
}
register_strings("search_documents", _STRINGS)


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
            return SkillResult(
                response_text=t_cached(_STRINGS, "empty_query", lang, "search_documents")
            )

        # Try hybrid search first (semantic + lexical)
        hybrid_results = await self._hybrid_search(query, context.family_id)
        if hybrid_results:
            return self._format_hybrid_results(query, hybrid_results, context.language or "en")

        # Fallback to plain ILIKE search
        return await self._ilike_search(query, context)

    async def _hybrid_search(
        self, query: str, family_id: str
    ) -> list[dict[str, Any]]:
        """Attempt hybrid semantic + lexical search."""
        try:
            from src.core.memory.document_vectors import search_documents_semantic

            return await search_documents_semantic(query, family_id, limit=10)
        except Exception as e:
            logger.debug("Hybrid search unavailable, falling back to ILIKE: %s", e)
            return []

    def _format_hybrid_results(
        self, query: str, results: list[dict[str, Any]], lang: str
    ) -> SkillResult:
        """Format hybrid search results."""
        ns = "search_documents"
        header = t_cached(_STRINGS, "header", lang, ns, count=len(results), query=query)
        lines = [header]

        for r in results:
            title = r.get("title") or r.get("file_name") or "Untitled"
            match_icon = "\U0001f50d" if "semantic" in r.get("match_type", "") else "\U0001f4c4"
            lines.append(f"{match_icon} <b>{title}</b>")

            chunk = r.get("chunk_text", "")
            if chunk:
                snippet = chunk[:150].replace("\n", " ")
                if len(chunk) > 150:
                    snippet += "..."
                lines.append(f"  <i>{snippet}</i>")

        return SkillResult(response_text="\n".join(lines))

    async def _ilike_search(
        self, query: str, context: SessionContext
    ) -> SkillResult:
        """Fallback ILIKE search (original logic)."""
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
        ns = "search_documents"
        if not docs:
            return SkillResult(
                response_text=t_cached(_STRINGS, "not_found", lang, ns, query=query)
            )

        header = t_cached(_STRINGS, "header", lang, ns, count=len(docs), query=query)
        lines = [header]
        for doc in docs:
            title = doc.title or doc.file_name or doc.type
            date_str = doc.created_at.strftime("%d.%m.%Y") if doc.created_at else ""
            lines.append(f"\U0001f4c4 <b>{title}</b> — {date_str}")

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
