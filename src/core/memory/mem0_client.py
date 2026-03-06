"""Layer 3: Mem0 — long-term memory with pgvector.

Supports domain segmentation: when `domain` is passed, user_id is scoped
to `{user_id}:{domain}` for namespace isolation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from mem0 import Memory

from src.core.circuit_breaker import get_circuit
from src.core.config import settings

if TYPE_CHECKING:
    from src.core.memory.mem0_domains import MemoryDomain

logger = logging.getLogger(__name__)

_memory: Memory | None = None

# Custom prompts for fact extraction (expanded beyond financial-only)
FACT_EXTRACTION_PROMPT = """Извлеки ВСЕ значимые факты из сообщения пользователя.
Игнорируй приветствия, вопросы без фактов, и шум.

Типы фактов:

ЛИЧНОСТЬ И ИДЕНТИЧНОСТЬ:
- user_identity: имя, возраст, профессия, город, страна, семья
- bot_identity: имя бота назначенное пользователем, роль, стиль обращения
- user_rule: явные правила ("без эмодзи", "коротко", "на русском", "зови себя X")
- user_preference: формат ответов, детальность, язык общения, тон

ПРОЕКТЫ И ЦЕЛИ:
- user_project: названия проектов, цели, статус, дедлайны

ФИНАНСЫ:
- profile: язык, валюта, бизнес-тип
- income: источники дохода, суммы, частота
- recurring_expense: регулярные платежи (аренда, страховка)
- budget_limit: лимиты бюджета по категориям
- merchant_mapping: какой мерчант → какая категория
- correction_rule: правила поправок пользователя
- spending_pattern: паттерны трат

ЖИЗНЬ:
- life_note: идеи, заметки, мысли пользователя (ключевые слова/теги)
- life_pattern: паттерны питания, настроения, энергии, сна
- life_preference: режим общения, предпочтения трекинга

ПРИОРИТЕТ извлечения (от высшего к низшему):
1. user_identity, bot_identity, user_rule — ВСЕГДА извлекай
2. user_project, user_preference — извлекай если явно указаны
3. Финансовые факты — извлекай при наличии сумм/категорий
4. Жизненные факты — извлекай при наличии трекинга

Ответь списком фактов или пустым списком если нет значимых фактов."""

# Backward-compatible alias
FINANCIAL_FACT_EXTRACTION_PROMPT = FACT_EXTRACTION_PROMPT

MEMORY_UPDATE_PROMPT = """Ты управляешь памятью пользователя.

Правила:
1. Добавляй (ADD) новые факты любого типа
2. Обновляй (UPDATE) устаревшие факты (новое имя, город, сумма, правило)
3. Удаляй (DELETE) явно опровергнутые факты
4. НИКОГДА не добавляй приветствия, вопросы, или общие фразы
5. Коррекции пользователя имеют ВЫСШИЙ приоритет
6. Правила пользователя (user_rule) и идентичность (user_identity, bot_identity) — критически важны
7. При противоречии — новый факт заменяет старый (temporal priority)"""

# Backward-compatible alias
FINANCIAL_MEMORY_UPDATE_PROMPT = MEMORY_UPDATE_PROMPT


def _build_pgvector_url(db_url: str) -> str:
    """Convert DATABASE_URL to a psycopg-compatible connection string.

    Handles:
    - Strips asyncpg driver prefix
    - Ensures sslmode=require for Supabase/Railway
    - Normalizes postgres:// → postgresql://
    """
    url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # Ensure sslmode=require for remote databases
    if "sslmode" not in params and parsed.hostname not in ("localhost", "127.0.0.1"):
        params["sslmode"] = ["require"]

    # NOTE: prepare_threshold is NOT a valid URI parameter for psycopg3.
    # It must be passed via connection kwargs, not the connection string.
    # Remove it if present in the URL to avoid "invalid URI query parameter" errors.
    params.pop("prepare_threshold", None)

    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def _create_connection_pool(connection_string: str):
    """Create a psycopg3 ConnectionPool with prepare_threshold=0.

    psycopg3 does NOT accept ``prepare_threshold`` as a URI query parameter.
    It must be passed via the ``kwargs`` dict so every connection in the pool
    disables automatic prepared statements — required for PgBouncer
    transaction-mode compatibility (Supavisor).
    """
    from psycopg_pool import ConnectionPool

    return ConnectionPool(
        conninfo=connection_string,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"prepare_threshold": 0},
    )


def get_memory() -> Memory:
    """Get or initialize Mem0 client."""
    global _memory
    if _memory is None:
        connection_string = _build_pgvector_url(settings.database_url)
        pool = _create_connection_pool(connection_string)
        config = {
            "llm": {
                "provider": "anthropic",
                "config": {
                    "model": "claude-haiku-4-5",
                    "api_key": settings.anthropic_api_key,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small",
                    "api_key": settings.openai_api_key,
                },
            },
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "dbname": "postgres",
                    "connection_string": connection_string,
                    "connection_pool": pool,
                    "collection_name": "mem0_memories",
                },
            },
            "custom_prompts": {
                "fact_extraction_prompt": FACT_EXTRACTION_PROMPT,
                "update_memory_prompt": MEMORY_UPDATE_PROMPT,
            },
        }
        _memory = Memory.from_config(config)
    return _memory


def _reset_memory() -> None:
    """Reset the Mem0 singleton (used on connection failures)."""
    global _memory
    _memory = None


def _resolve_user_id(user_id: str, domain: MemoryDomain | None) -> str:
    """Scope user_id by domain for namespace isolation."""
    if domain is None:
        return user_id
    from src.core.memory.mem0_domains import scoped_user_id

    return scoped_user_id(user_id, domain)


async def search_memories(
    query: str,
    user_id: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    domain: MemoryDomain | None = None,
) -> list[dict]:
    """Search Mem0 for relevant memories.

    When *domain* is set, searches only that domain's namespace.
    """
    cb = get_circuit("mem0")
    if not cb.can_execute():
        logger.warning("Mem0 circuit OPEN, skipping search")
        return []
    try:
        memory = get_memory()
        scoped_uid = _resolve_user_id(user_id, domain)
        kwargs: dict[str, Any] = {"query": query, "user_id": scoped_uid, "limit": limit}
        if filters:
            kwargs["filters"] = filters
        results = memory.search(**kwargs)
        cb.record_success()
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception as e:
        logger.error("Mem0 search failed: %s", e)
        cb.record_failure()
        _reset_memory()
        return []


async def search_memories_multi_domain(
    query: str,
    user_id: str,
    domains: list[MemoryDomain],
    limit_per_domain: int = 5,
) -> list[dict]:
    """Search across multiple domains and merge results with fuzzy dedup."""
    import asyncio

    from src.core.text_utils import is_similar

    tasks = [
        search_memories(query, user_id, limit=limit_per_domain, domain=d)
        for d in domains
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged: list[dict] = []
    seen_texts: list[str] = []
    for r in results:
        if isinstance(r, list):
            for mem in r:
                text = mem.get("memory") or mem.get("text") or ""
                if not text:
                    merged.append(mem)
                    continue
                if not any(is_similar(text, s) for s in seen_texts):
                    seen_texts.append(text)
                    merged.append(mem)
    return merged


async def _archive_superseded_fact(
    content: str,
    user_id: str,
    domain: MemoryDomain | None,
    original_category: str,
) -> None:
    """Archive old value before Mem0 overwrites it (temporal fact tracking).

    Searches for existing similar fact; if found with high similarity,
    stores the old value as a ``fact_history`` entry with timestamps.
    """
    from datetime import date

    from src.core.memory.mem0_domains import (
        TEMPORAL_SIMILARITY_THRESHOLD,
        UPDATABLE_CATEGORIES,
    )

    if original_category not in UPDATABLE_CATEGORIES:
        return

    try:
        existing = await search_memories(content, user_id, limit=1, domain=domain)
        if not existing:
            return
        top = existing[0]
        score = top.get("score", 0)
        if score < TEMPORAL_SIMILARITY_THRESHOLD:
            return
        old_text = top.get("memory", top.get("text", ""))
        if not old_text or old_text == content:
            return
        archive_meta = {
            "category": "fact_history",
            "superseded_at": date.today().isoformat(),
            "old_value": old_text,
            "new_value": content,
            "original_category": original_category,
        }
        memory = get_memory()
        scoped_uid = _resolve_user_id(user_id, domain)
        memory.add(f"[Archived] {old_text}", user_id=scoped_uid, metadata=archive_meta)
    except Exception as e:
        logger.debug("Temporal archive failed (non-critical): %s", e)



# Phase 7: Priority mapping for fact categories
_CATEGORY_PRIORITY: dict[str, str] = {
    "user_identity": "critical",
    "bot_identity": "critical",
    "user_rule": "critical",
    "user_preference": "critical",
    "profile": "critical",
    "user_project": "important",
    "income": "important",
    "recurring_expense": "important",
    "budget_limit": "important",
    "merchant_mapping": "normal",
    "correction_rule": "normal",
    "spending_pattern": "normal",
    "life_note": "normal",
    "life_pattern": "normal",
    "life_preference": "normal",
}


def _enrich_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Add priority and updated_at to metadata (Phase 7)."""
    from datetime import date

    meta = dict(metadata) if metadata else {}
    category = meta.get("category", "")

    # Add priority based on category
    if "priority" not in meta:
        meta["priority"] = _CATEGORY_PRIORITY.get(category, "normal")

    # Add temporal updated_at
    if "updated_at" not in meta:
        meta["updated_at"] = date.today().isoformat()

    return meta


async def add_memory(
    content: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
    domain: MemoryDomain | None = None,
) -> dict:
    """Add a memory to Mem0.

    When *domain* is set, stores in that domain's namespace.
    If not set, auto-derives domain from metadata category.
    Temporal tracking: archives superseded facts for updatable categories.
    Phase 7: Enriches metadata with priority and updated_at.
    """
    metadata = _enrich_metadata(metadata)
    cb = get_circuit("mem0")
    if not cb.can_execute():
        logger.warning("Mem0 circuit OPEN, skipping add — enqueueing to DLQ")
        try:
            from src.core.memory.mem0_dlq import enqueue_failed_memory

            await enqueue_failed_memory(user_id, content, metadata)
        except Exception as dlq_err:
            logger.error("Mem0 DLQ enqueue failed (circuit open path): %s", dlq_err)
        return {}
    try:
        # Auto-derive domain from metadata category if not explicitly set
        if domain is None and metadata and "category" in metadata:
            from src.core.memory.mem0_domains import get_domain_for_category

            domain = get_domain_for_category(metadata["category"])

        # Temporal tracking: archive old fact before overwrite
        category = (metadata or {}).get("category", "")
        if category and category != "fact_history":
            await _archive_superseded_fact(content, user_id, domain, category)

        memory = get_memory()
        scoped_uid = _resolve_user_id(user_id, domain)
        result = memory.add(content, user_id=scoped_uid, metadata=metadata or {})
        cb.record_success()
        return result
    except Exception as e:
        logger.error("Mem0 add failed for user %s: %s", user_id, e)
        cb.record_failure()
        _reset_memory()
        # Enqueue to DLQ so the write is retried later
        try:
            from src.core.memory.mem0_dlq import enqueue_failed_memory

            await enqueue_failed_memory(user_id, content, metadata)
        except Exception as dlq_err:
            logger.error("Mem0 DLQ enqueue also failed: %s", dlq_err)
        return {}


async def get_all_memories(
    user_id: str,
    domain: MemoryDomain | None = None,
) -> list[dict]:
    """Get all memories for a user (optionally scoped to a domain)."""
    cb = get_circuit("mem0")
    if not cb.can_execute():
        logger.warning("Mem0 circuit OPEN, skipping get_all")
        return []
    try:
        memory = get_memory()
        scoped_uid = _resolve_user_id(user_id, domain)
        results = memory.get_all(user_id=scoped_uid)
        cb.record_success()
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception as e:
        logger.error("Mem0 get_all failed: %s", e)
        cb.record_failure()
        _reset_memory()
        return []


async def delete_memory(memory_id: str, user_id: str) -> None:
    """Delete a single memory by its ID."""
    cb = get_circuit("mem0")
    if not cb.can_execute():
        logger.warning("Mem0 circuit OPEN, skipping delete")
        return
    try:
        memory = get_memory()
        memory.delete(memory_id=memory_id)
        cb.record_success()
    except Exception as e:
        logger.warning("Mem0 delete_memory(%s) failed: %s", memory_id, e)
        cb.record_failure()
        _reset_memory()


async def delete_all_memories(user_id: str) -> None:
    """Delete all memories for a user (GDPR)."""
    cb = get_circuit("mem0")
    if not cb.can_execute():
        logger.warning("Mem0 circuit OPEN, skipping delete_all")
        return
    try:
        memory = get_memory()
        memory.delete_all(user_id=user_id)
        cb.record_success()
    except Exception as e:
        logger.warning("Mem0 delete_all failed: %s", e)
        cb.record_failure()
        _reset_memory()
