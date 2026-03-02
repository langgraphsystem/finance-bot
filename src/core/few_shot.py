"""Dynamic few-shot example retrieval for intent detection.

Uses pgvector to find semantically similar past user messages
and their correct intent classifications. Learns from corrections.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.5
DEFAULT_LIMIT = 3


async def get_embedding(text: str) -> list[float] | None:
    """Get embedding for text via OpenAI."""
    try:
        import openai

        client = openai.AsyncOpenAI()
        resp = await client.embeddings.create(
            model="text-embedding-3-small", input=text
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("Failed to get embedding: %s", e)
        return None


async def retrieve_few_shot_examples(
    user_message: str,
    family_id: str,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve top-K semantically similar few-shot examples."""
    if not user_message.strip():
        return []

    embedding = await get_embedding(user_message)
    if not embedding:
        return []

    try:
        from sqlalchemy import text

        from src.core.db import async_session

        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT id, user_message, detected_intent, corrected_intent,
                           intent_data,
                           1 - (embedding <=> :emb::vector) as similarity
                    FROM few_shot_examples
                    WHERE family_id = :fid
                      AND 1 - (embedding <=> :emb::vector) >= :min_sim
                    ORDER BY similarity DESC
                    LIMIT :lim
                """),
                {
                    "fid": family_id,
                    "emb": str(embedding),
                    "min_sim": MIN_SIMILARITY,
                    "lim": limit,
                },
            )
            rows = result.all()

        return [
            {
                "id": str(r.id),
                "user_message": r.user_message,
                "detected_intent": r.detected_intent,
                "corrected_intent": r.corrected_intent,
                "intent_data": r.intent_data,
                "similarity": r.similarity,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to retrieve few-shot examples: %s", e)
        return []


def format_few_shot_block(examples: list[dict]) -> str:
    """Format few-shot examples as XML block for system prompt injection."""
    if not examples:
        return ""

    lines = ["<few_shot_examples>"]
    for ex in examples:
        intent = ex.get("corrected_intent") or ex.get("detected_intent", "")
        lines.append("  <example>")
        lines.append(f"    <user_message>{ex['user_message']}</user_message>")
        lines.append(f"    <intent>{intent}</intent>")
        if ex.get("intent_data"):
            data = ex["intent_data"]
            if isinstance(data, dict):
                for k, v in data.items():
                    if v is not None:
                        lines.append(f"    <{k}>{v}</{k}>")
        lines.append("  </example>")
    lines.append("</few_shot_examples>")
    return "\n".join(lines)


async def save_few_shot_example(
    family_id: str,
    user_message: str,
    detected_intent: str,
    corrected_intent: str | None = None,
    intent_data: dict | None = None,
) -> str | None:
    """Save a new few-shot example with embedding. Returns example ID or None."""
    embedding = await get_embedding(user_message)
    if not embedding:
        return None

    try:
        from sqlalchemy import text

        from src.core.db import async_session

        async with async_session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO few_shot_examples
                    (family_id, user_message, detected_intent, corrected_intent,
                     intent_data, embedding)
                    VALUES (:fid, :msg, :det, :cor, :data, :emb::vector)
                    RETURNING id
                """),
                {
                    "fid": family_id,
                    "msg": user_message,
                    "det": detected_intent,
                    "cor": corrected_intent,
                    "data": str(intent_data) if intent_data else None,
                    "emb": str(embedding),
                },
            )
            row = result.first()
            await session.commit()
            return str(row.id) if row else None
    except Exception as e:
        logger.warning("Failed to save few-shot example: %s", e)
        return None


async def increment_usage(example_id: str) -> None:
    """Increment usage count for a few-shot example."""
    try:
        from sqlalchemy import text

        from src.core.db import async_session

        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE few_shot_examples
                    SET usage_count = usage_count + 1
                    WHERE id = :id
                """),
                {"id": example_id},
            )
            await session.commit()
    except Exception as e:
        logger.warning("Failed to increment few-shot usage: %s", e)
