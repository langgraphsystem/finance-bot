"""Layer 3: Mem0 — long-term memory with pgvector."""

import logging
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from mem0 import Memory

from src.core.config import settings

logger = logging.getLogger(__name__)

_memory: Memory | None = None

# Custom prompts for financial fact extraction
FINANCIAL_FACT_EXTRACTION_PROMPT = """Извлеки ТОЛЬКО финансовые факты из сообщения пользователя.
Игнорируй приветствия, вопросы, и нефинансовую информацию.

Типы фактов:
- profile: язык, валюта, бизнес-тип
- income: источники дохода, суммы, частота
- recurring_expense: регулярные платежи (аренда, страховка)
- budget_limit: лимиты бюджета по категориям
- merchant_mapping: какой мерчант → какая категория
- correction_rule: правила поправок пользователя
- spending_pattern: паттерны трат
- life_note: идеи, заметки, мысли пользователя (ключевые слова/теги)
- life_pattern: паттерны питания, настроения, энергии, сна
- life_preference: режим общения, предпочтения трекинга, проекты

Ответь списком фактов или пустым списком если нет финансовых фактов."""

FINANCIAL_MEMORY_UPDATE_PROMPT = """Ты управляешь финансовой памятью пользователя.

Правила:
1. Добавляй (ADD) новые финансовые факты
2. Обновляй (UPDATE) устаревшие факты (новая сумма, новый мерчант)
3. Удаляй (DELETE) явно опровергнутые факты
4. НИКОГДА не добавляй приветствия, вопросы, или общие фразы
5. Коррекции пользователя имеют приоритет — если юзер исправляет категорию, обнови маппинг"""


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

    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def get_memory() -> Memory:
    """Get or initialize Mem0 client."""
    global _memory
    if _memory is None:
        connection_string = _build_pgvector_url(settings.database_url)
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
                    "collection_name": "mem0_memories",
                },
            },
            "custom_prompts": {
                "fact_extraction_prompt": FINANCIAL_FACT_EXTRACTION_PROMPT,
                "update_memory_prompt": FINANCIAL_MEMORY_UPDATE_PROMPT,
            },
        }
        _memory = Memory.from_config(config)
    return _memory


def _reset_memory() -> None:
    """Reset the Mem0 singleton (used on connection failures)."""
    global _memory
    _memory = None


async def search_memories(
    query: str,
    user_id: str,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """Search Mem0 for relevant memories."""
    try:
        memory = get_memory()
        kwargs: dict[str, Any] = {"query": query, "user_id": user_id, "limit": limit}
        if filters:
            kwargs["filters"] = filters
        results = memory.search(**kwargs)
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception as e:
        logger.warning("Mem0 search failed: %s", e)
        _reset_memory()
        return []


async def add_memory(
    content: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Add a memory to Mem0."""
    try:
        memory = get_memory()
        return memory.add(content, user_id=user_id, metadata=metadata or {})
    except Exception as e:
        logger.warning("Mem0 add failed: %s", e)
        _reset_memory()
        return {}


async def get_all_memories(user_id: str) -> list[dict]:
    """Get all memories for a user."""
    try:
        memory = get_memory()
        results = memory.get_all(user_id=user_id)
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception as e:
        logger.warning("Mem0 get_all failed: %s", e)
        _reset_memory()
        return []


async def delete_all_memories(user_id: str) -> None:
    """Delete all memories for a user (GDPR)."""
    try:
        memory = get_memory()
        memory.delete_all(user_id=user_id)
    except Exception as e:
        logger.warning("Mem0 delete_all failed: %s", e)
        _reset_memory()
