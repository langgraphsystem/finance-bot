"""Life search skill — hybrid semantic + SQL search across life events and memories."""

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    _type_icon,
    format_timeline,
    query_life_events,
    resolve_life_period,
)
from src.core.memory.mem0_client import search_memories
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """Ты помогаешь пользователю найти записи в дневнике жизни.
Объедини результаты из базы данных и семантической памяти.
Покажи результаты как таймлайн."""

_DEDUP_SIMILARITY_THRESHOLD = 0.75


def _resolve_event_type(raw: str | None) -> LifeEventType | None:
    """Convert string to LifeEventType, return None if invalid."""
    if not raw:
        return None
    try:
        return LifeEventType(raw)
    except ValueError:
        return None


def _normalize_text(text: str) -> str:
    """Normalize text for deduplication comparison."""
    return " ".join(text.lower().strip().split())


def _is_duplicate(text1: str, text2: str) -> bool:
    """Check if two texts are near-duplicates using similarity comparison."""
    t1 = _normalize_text(text1)
    t2 = _normalize_text(text2)
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    # Containment check for short-in-long matches
    if t1 in t2 or t2 in t1:
        return True
    return SequenceMatcher(None, t1, t2).ratio() >= _DEDUP_SIMILARITY_THRESHOLD


class LifeSearchSkill:
    name = "life_search"
    intents = ["life_search"]
    model = "gpt-5.2"

    @observe(name="life_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = intent_data.get("search_query") or message.text or ""

        # Parse period from intent_data
        date_from, date_to, period_label = resolve_life_period(intent_data)

        # If no query AND no period filter, ask what to search for
        if not query.strip() and not date_from:
            return SkillResult(response_text="Что искать? Напишите запрос.")

        # Parse event type filter
        event_type = _resolve_event_type(intent_data.get("life_event_type"))

        # If we have a period or type filter, skip ILIKE
        # (temporal queries like "что я ел вчера?" produce bad ILIKE matches)
        use_text_search = not date_from and not event_type

        # 1. SQL search on life_events
        sql_events = await query_life_events(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            search_text=query.strip() if use_text_search else None,
            limit=30,
        )

        # 2. Mem0 semantic search — always run when we have a query
        # Finds semantically related memories even when SQL uses date/type filters
        mem0_results: list[dict] = []
        if query.strip():
            try:
                mem0_results = await search_memories(
                    query=query.strip(),
                    user_id=context.user_id,
                    limit=10,
                )
            except Exception as e:
                logger.warning("Mem0 search failed: %s", e)

        # Merge results: SQL events as primary, Mem0 as supplementary
        # Use similarity-based dedup to avoid near-duplicate entries
        timeline_events = list(sql_events)
        sql_texts = [ev.text for ev in sql_events if ev.text]
        for mem in mem0_results:
            mem_text = mem.get("memory") or mem.get("text") or ""
            if not mem_text:
                continue
            if not any(_is_duplicate(mem_text, st) for st in sql_texts):
                timeline_events.append(_mem0_to_pseudo_event(mem))

        if not timeline_events:
            no_result = f"По запросу <b>«{query}»</b>"
            if period_label:
                no_result += f" за {period_label}"
            no_result += " ничего не найдено."
            return SkillResult(response_text=no_result)

        # Build rich header
        header = "<b>Результаты"
        if period_label:
            header += f" за {period_label}"
        header += f"</b>  ({len(timeline_events)})\n"
        if event_type:
            header += f"Фильтр: {_type_icon(event_type)} {event_type.value}\n"

        formatted = format_timeline(timeline_events, max_events=20)

        # Buttons for quick period switching
        buttons = [
            {"text": "\U0001f4c5 Сегодня", "callback": "life_search:today"},
            {"text": "\U0001f4c5 Неделя", "callback": "life_search:week"},
            {"text": "\U0001f4c5 Месяц", "callback": "life_search:month"},
        ]

        return SkillResult(
            response_text=header + formatted,
            buttons=buttons,
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        return prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)


class _PseudoLifeEvent:
    """Lightweight stand-in for LifeEvent so format_timeline can render Mem0 hits."""

    def __init__(self, mem: dict):
        from datetime import date as _date
        from datetime import datetime

        self.text = mem.get("memory") or mem.get("text") or ""
        meta = mem.get("metadata")
        self.tags = meta.get("tags") if isinstance(meta, dict) else None
        self.type = _resolve_mem0_type(mem)
        self.data = None
        self.score = mem.get("score", 0.0)
        raw_date = mem.get("created_at") or mem.get("updated_at")
        if raw_date:
            try:
                dt = datetime.fromisoformat(str(raw_date))
                self.date = dt.date()
                self.created_at = dt
            except (ValueError, TypeError):
                self.date = _date.today()
                self.created_at = datetime.now()
        else:
            self.date = _date.today()
            self.created_at = datetime.now()


def _resolve_mem0_type(mem: dict) -> LifeEventType:
    """Attempt to determine LifeEventType from Mem0 metadata."""
    meta = mem.get("metadata") or {}
    raw_type = meta.get("type", "note") if isinstance(meta, dict) else "note"
    try:
        return LifeEventType(raw_type)
    except ValueError:
        return LifeEventType.note


def _mem0_to_pseudo_event(mem: dict) -> Any:
    return _PseudoLifeEvent(mem)


skill = LifeSearchSkill()
