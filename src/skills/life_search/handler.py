"""Life search skill — semantic + SQL search across life events and memories."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import format_timeline, query_life_events
from src.core.memory.mem0_client import search_memories
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

LIFE_SEARCH_SYSTEM_PROMPT = """Ты помогаешь пользователю найти записи в дневнике жизни.
Объедини результаты из базы данных и семантической памяти.
Покажи результаты как таймлайн."""


class LifeSearchSkill:
    name = "life_search"
    intents = ["life_search"]
    model = "claude-haiku-4-5"

    @observe(name="life_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = intent_data.get("search_query") or message.text or ""

        if not query.strip():
            return SkillResult(response_text="Что искать? Напишите запрос.")

        # 1. SQL search on life_events
        sql_events = await query_life_events(
            family_id=context.family_id,
            user_id=context.user_id,
            search_text=query.strip(),
            limit=15,
        )

        # 2. Mem0 semantic search
        mem0_results: list[dict] = []
        try:
            mem0_results = await search_memories(
                query=query.strip(),
                user_id=context.user_id,
                limit=10,
            )
        except Exception as e:
            logger.warning("Mem0 search failed: %s", e)

        # Merge results: SQL events as primary, Mem0 as supplementary
        # Convert LifeEvent objects to dicts for format_timeline
        timeline_events = sql_events

        # Append Mem0 results that aren't already in SQL results
        sql_texts = {ev.text for ev in sql_events if ev.text}
        for mem in mem0_results:
            mem_text = mem.get("memory") or mem.get("text") or ""
            if mem_text and mem_text not in sql_texts:
                timeline_events.append(_mem0_to_pseudo_event(mem))

        if not timeline_events:
            return SkillResult(response_text=f"По запросу <b>«{query}»</b> ничего не найдено.")

        formatted = format_timeline(timeline_events)
        header = f"<b>Результаты по «{query}»:</b>\n"
        return SkillResult(response_text=header + formatted)

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIFE_SEARCH_SYSTEM_PROMPT


class _PseudoLifeEvent:
    """Lightweight stand-in for LifeEvent so format_timeline can render Mem0 hits."""

    def __init__(self, mem: dict):
        from datetime import date, datetime

        self.text = mem.get("memory") or mem.get("text") or ""
        meta = mem.get("metadata")
        self.tags = meta.get("tags") if isinstance(meta, dict) else None
        self.type = _resolve_type(mem)
        raw_date = mem.get("created_at") or mem.get("updated_at")
        if raw_date:
            try:
                dt = datetime.fromisoformat(str(raw_date))
                self.date = dt.date()
                self.created_at = dt
            except (ValueError, TypeError):
                self.date = date.today()
                self.created_at = datetime.now()
        else:
            self.date = date.today()
            self.created_at = datetime.now()


def _resolve_type(mem: dict):
    """Attempt to determine LifeEventType from Mem0 metadata."""
    from src.core.models.enums import LifeEventType

    meta = mem.get("metadata") or {}
    raw_type = meta.get("type", "note") if isinstance(meta, dict) else "note"
    try:
        return LifeEventType(raw_type)
    except ValueError:
        return LifeEventType.note


def _mem0_to_pseudo_event(mem: dict) -> Any:
    return _PseudoLifeEvent(mem)


skill = LifeSearchSkill()
