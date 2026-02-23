"""Dynamic few-shot example retrieval for intent detection.

Retrieves semantically similar few-shot examples from the few_shot_examples table
using pgvector cosine similarity. Injected into the intent detection prompt to
improve accuracy based on user-specific corrections and patterns.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import text

from src.core.db import async_session
from src.core.embeddings import get_embedding
from src.core.models.few_shot_example import FewShotExample
from src.core.observability import observe

logger = logging.getLogger(__name__)

# Max examples to inject into intent prompt
DEFAULT_LIMIT = 3
# Minimum similarity score (cosine) to include an example
MIN_SIMILARITY = 0.5


@observe(name="few_shot_retrieve")
async def retrieve_few_shot_examples(
    user_message: str,
    family_id: str,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve top-K few-shot examples by semantic similarity.

    Returns list of dicts with keys: user_message, intent, intent_data, score.
    Falls back gracefully to empty list on any error.
    """
    if not user_message.strip():
        return []

    try:
        embedding = await get_embedding(user_message)
    except Exception as e:
        logger.warning("Few-shot embedding generation failed: %s", e)
        return []

    try:
        return await _search_by_embedding(embedding, family_id, limit)
    except Exception as e:
        logger.warning("Few-shot retrieval failed: %s", e)
        return []


async def _search_by_embedding(
    embedding: list[float],
    family_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Search few_shot_examples by cosine similarity using pgvector."""
    async with async_session() as session:
        query = text("""
            SELECT
                user_message,
                COALESCE(corrected_intent, detected_intent) AS intent,
                intent_data,
                1 - (embedding <=> :embedding::vector) AS similarity
            FROM few_shot_examples
            WHERE family_id = :family_id
              AND embedding IS NOT NULL
              AND accuracy_score >= 0.5
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """)

        result = await session.execute(
            query,
            {
                "embedding": str(embedding),
                "family_id": family_id,
                "limit": limit,
            },
        )
        rows = result.fetchall()

    examples = []
    for row in rows:
        similarity = float(row.similarity)
        if similarity < MIN_SIMILARITY:
            continue
        examples.append(
            {
                "user_message": row.user_message,
                "intent": row.intent,
                "intent_data": row.intent_data,
                "score": similarity,
            }
        )

    return examples


def format_few_shot_block(examples: list[dict[str, Any]]) -> str:
    """Format few-shot examples as an XML block for injection into system prompt.

    Returns empty string if no examples — zero-shot behavior preserved.
    """
    if not examples:
        return ""

    lines = ["\n\n<few_shot_examples>"]
    for i, ex in enumerate(examples, 1):
        intent = ex["intent"]
        msg = ex["user_message"]
        lines.append(f"<example_{i}>")
        lines.append(f"  User: {msg}")
        lines.append(f"  Intent: {intent}")
        if ex.get("intent_data"):
            data = ex["intent_data"]
            fields = {k: v for k, v in data.items() if v is not None}
            if fields:
                lines.append(f"  Data: {fields}")
        lines.append(f"</example_{i}>")
    lines.append("</few_shot_examples>")

    return "\n".join(lines)


async def save_few_shot_example(
    family_id: str,
    user_message: str,
    detected_intent: str,
    corrected_intent: str | None = None,
    intent_data: dict[str, Any] | None = None,
) -> FewShotExample | None:
    """Save a few-shot example with embedding. Used by correction flows."""
    try:
        embedding = await get_embedding(user_message)
    except Exception as e:
        logger.warning("Few-shot save embedding failed: %s", e)
        return None

    try:
        async with async_session() as session:
            example = FewShotExample(
                family_id=uuid.UUID(family_id),
                user_message=user_message,
                detected_intent=detected_intent,
                corrected_intent=corrected_intent,
                intent_data=intent_data,
            )
            session.add(example)
            await session.flush()
            example_id = example.id

            await session.execute(
                text("UPDATE few_shot_examples SET embedding = :emb::vector WHERE id = :id"),
                {"emb": str(embedding), "id": example_id},
            )
            await session.commit()
            return example
    except Exception as e:
        logger.warning("Few-shot save failed: %s", e)
        return None


async def increment_usage(example_id: str) -> None:
    """Increment usage_count for a few-shot example (called after successful use)."""
    try:
        async with async_session() as session:
            await session.execute(
                text("UPDATE few_shot_examples SET usage_count = usage_count + 1 WHERE id = :id"),
                {"id": uuid.UUID(example_id)},
            )
            await session.commit()
    except Exception as e:
        logger.warning("Few-shot usage increment failed: %s", e)
