"""Hybrid RAG categorization: rules -> vector search -> LLM."""

import logging
import uuid

from sqlalchemy import func, select, text

from src.core.db import async_session
from src.core.llm.clients import get_instructor_anthropic, openai_client
from src.core.models.category import Category
from src.core.models.merchant_mapping import MerchantMapping
from src.core.observability import observe

logger = logging.getLogger(__name__)


class CategoryPrediction:
    """Result of categorization."""

    def __init__(self, category_id: str, category_name: str, confidence: float, method: str):
        self.category_id = category_id
        self.category_name = category_name
        self.confidence = confidence
        self.method = method  # "rule", "rag", "llm"

    def __repr__(self) -> str:
        return (
            f"CategoryPrediction(category='{self.category_name}', "
            f"confidence={self.confidence:.2f}, method='{self.method}')"
        )


@observe(name="categorize_transaction")
async def categorize_transaction(
    description: str,
    merchant: str | None,
    family_id: str,
    available_categories: list[dict],
) -> CategoryPrediction | None:
    """Hybrid categorization pipeline.

    Steps:
        1. Rule-based matching from merchant_mappings table.
        2. pgvector similarity search for similar past transactions.
        3. LLM classification with context from previous steps.
    """

    # Step 1: Rule-based matching from merchant_mappings
    if merchant:
        rule_result = await _match_by_rules(merchant, family_id)
        if rule_result:
            return rule_result

    # Step 2: Vector similarity search (if pgvector is available)
    rag_result = await _match_by_similarity(description, family_id, available_categories)
    if rag_result and rag_result.confidence >= 0.7:
        return rag_result

    # Step 3: LLM classification with context
    llm_result = await _classify_with_llm(
        description,
        merchant,
        available_categories,
        rag_context=rag_result,
    )
    return llm_result


async def _match_by_rules(merchant: str, family_id: str) -> CategoryPrediction | None:
    """Step 1: Rule-based matching from merchant_mappings table."""
    async with async_session() as session:
        result = await session.execute(
            select(MerchantMapping, Category.name)
            .join(Category, MerchantMapping.category_id == Category.id)
            .where(
                MerchantMapping.family_id == uuid.UUID(family_id),
                func.lower(MerchantMapping.merchant_pattern) == merchant.lower(),
            )
            .order_by(MerchantMapping.usage_count.desc())
            .limit(1)
        )
        row = result.first()
        if row:
            mapping, cat_name = row
            confidence = min(float(mapping.usage_count) / 100, 0.99)
            return CategoryPrediction(
                category_id=str(mapping.category_id),
                category_name=cat_name,
                confidence=max(confidence, 0.6),
                method="rule",
            )
    return None


async def _match_by_similarity(
    description: str,
    family_id: str,
    available_categories: list[dict],
) -> CategoryPrediction | None:
    """Step 2: pgvector similarity search for similar past transactions."""
    try:
        # Get embedding for the description
        client = openai_client()
        embedding_response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=description,
        )
        query_embedding = embedding_response.data[0].embedding

        # Search similar transactions using pgvector
        async with async_session() as session:
            # Check if embedding column exists (graceful degradation)
            try:
                result = await session.execute(
                    text("""
                        SELECT t.description, c.name as category_name, c.id as category_id,
                               COUNT(*) as freq,
                               1 - (t.embedding <=> :embedding::vector) as similarity
                        FROM transactions t
                        JOIN categories c ON t.category_id = c.id
                        WHERE t.family_id = :family_id
                          AND t.embedding IS NOT NULL
                        GROUP BY t.description, c.name, c.id, t.embedding
                        ORDER BY t.embedding <=> :embedding::vector
                        LIMIT 5
                    """),
                    {"family_id": family_id, "embedding": str(query_embedding)},
                )
                similar = result.all()
            except Exception:
                logger.debug("pgvector search not available, skipping")
                return None

            if not similar:
                return None

            # Determine most common category among similar transactions
            category_counts: dict[str, tuple[str, int, float]] = {}
            for desc, cat_name, cat_id, freq, sim in similar:
                key = str(cat_id)
                if key in category_counts:
                    _, old_freq, old_sim = category_counts[key]
                    category_counts[key] = (cat_name, old_freq + freq, max(old_sim, sim))
                else:
                    category_counts[key] = (cat_name, freq, sim)

            # Pick the best match
            best_id = max(category_counts, key=lambda k: category_counts[k][1])
            best_name, best_freq, best_sim = category_counts[best_id]
            confidence = min(best_sim * 0.8 + (best_freq / 10) * 0.2, 0.95)

            return CategoryPrediction(
                category_id=best_id,
                category_name=best_name,
                confidence=confidence,
                method="rag",
            )
    except Exception as e:
        logger.warning("Vector similarity search failed: %s", e)
        return None


async def _classify_with_llm(
    description: str,
    merchant: str | None,
    available_categories: list[dict],
    rag_context: CategoryPrediction | None = None,
) -> CategoryPrediction | None:
    """Step 3: LLM classification with context."""
    from pydantic import BaseModel, Field

    class CategoryChoice(BaseModel):
        category_name: str = Field(description="Category name from the list")
        confidence: float = Field(ge=0, le=1, description="Confidence 0-1")

    categories_text = "\n".join(f"- {c['name']} (id: {c['id']})" for c in available_categories)

    context = ""
    if rag_context:
        context = f"\nПохожие транзакции ранее относились к: {rag_context.category_name}"

    merchant_line = f"Магазин: {merchant}\n" if merchant else ""
    prompt = (
        f"Категоризируй транзакцию:\n"
        f"Описание: {description}\n"
        f"{merchant_line}"
        f"{context}\n\n"
        f"Доступные категории:\n{categories_text}\n\n"
        f"Выбери наиболее подходящую категорию."
    )

    try:
        client = get_instructor_anthropic()
        result = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            response_model=CategoryChoice,
            max_retries=2,
            messages=[{"role": "user", "content": prompt}],
        )

        # Find matching category ID
        cat_id = None
        for c in available_categories:
            if c["name"].lower() == result.category_name.lower():
                cat_id = c["id"]
                break

        if not cat_id and available_categories:
            cat_id = available_categories[0]["id"]
            result.category_name = available_categories[0]["name"]

        return CategoryPrediction(
            category_id=cat_id or "",
            category_name=result.category_name,
            confidence=result.confidence,
            method="llm",
        )
    except Exception as e:
        logger.error("LLM categorization failed: %s", e)
        return None
