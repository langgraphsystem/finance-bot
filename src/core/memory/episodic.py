"""Episodic Memory — "Do the same as last time" (Phase 3.2).

Stores and retrieves complete episode metadata for generative skills.
An episode captures: topics, intents used, outcome, satisfaction,
and skill-specific result metadata (e.g., slides count, style).

Episodes are stored as metadata on session_summaries and in Mem0
under the ``episodes`` domain for semantic search.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.session_summary import SessionSummary
from src.core.observability import observe

logger = logging.getLogger(__name__)

# Max episodes to return in context
MAX_EPISODE_CONTEXT = 3

# Intents that benefit from episodic context (generative/complex)
EPISODIC_INTENTS: frozenset[str] = frozenset({
    "generate_presentation",
    "generate_spreadsheet",
    "generate_document",
    "draft_message",
    "draft_reply",
    "write_post",
    "generate_image",
    "generate_card",
    "generate_program",
    "complex_query",
    "financial_summary",
    "morning_brief",
    "send_email",
})

EPISODE_EXTRACTION_PROMPT = """Проанализируй диалог и извлеки метаданные эпизода.

САММАРИ ДИАЛОГА:
{summary}

Ответь в JSON формате:
{{
  "topics": ["тема1", "тема2"],
  "intents_used": ["intent1", "intent2"],
  "outcome": "completed|abandoned|error",
  "satisfaction": "positive|neutral|negative",
  "key_params": {{}}
}}

ПРАВИЛА:
1. topics — основные темы обсуждения (2-5)
2. intents_used — какие навыки были задействованы
3. outcome — результат: completed (успех), abandoned (бросил), error (ошибка)
4. satisfaction — по тону сообщений: positive (спасибо, отлично), negative (нет, неправильно)
5. key_params — ключевые параметры задачи (стиль, формат, получатель и т.д.)

JSON:"""


@observe(name="store_episode")
async def store_episode(
    user_id: str,
    family_id: str,
    intent: str,
    result_metadata: dict[str, Any] | None = None,
) -> None:
    """Store episode metadata on the most recent session summary.

    Called after successful execution of generative skills.
    """
    try:
        async with async_session() as session:
            result = await session.execute(
                select(SessionSummary)
                .where(SessionSummary.user_id == uuid.UUID(user_id))
                .order_by(SessionSummary.updated_at.desc())
                .limit(1)
            )
            summary = result.scalar_one_or_none()
            if not summary:
                return

            episode_data = {
                "intent": intent,
                "timestamp": datetime.now(UTC).isoformat(),
                "result": result_metadata or {},
            }

            existing_meta = summary.episode_metadata or {}
            episodes = existing_meta.get("episodes", [])
            episodes.append(episode_data)
            # Keep last 10 episodes per summary
            existing_meta["episodes"] = episodes[-10:]
            summary.episode_metadata = existing_meta
            await session.commit()
            logger.debug("Stored episode for user %s intent %s", user_id, intent)
    except Exception as e:
        logger.debug("Episode storage failed: %s", e)


@observe(name="search_episodes")
async def search_episodes(
    user_id: str,
    topic: str,
    intent: str | None = None,
    limit: int = MAX_EPISODE_CONTEXT,
) -> list[dict[str, Any]]:
    """Search past episodes relevant to a topic/intent.

    Returns episode metadata dicts sorted by recency.
    """
    try:
        async with async_session() as session:
            query = (
                select(SessionSummary)
                .where(
                    SessionSummary.user_id == uuid.UUID(user_id),
                    SessionSummary.episode_metadata.isnot(None),
                )
                .order_by(SessionSummary.updated_at.desc())
                .limit(20)
            )
            result = await session.execute(query)
            summaries = list(result.scalars().all())

        matched: list[dict[str, Any]] = []
        topic_lower = topic.lower()

        for s in summaries:
            meta = s.episode_metadata or {}
            episodes = meta.get("episodes", [])
            for ep in episodes:
                # Match by intent
                if intent and ep.get("intent") == intent:
                    matched.append({
                        **ep,
                        "summary": s.summary[:200],
                        "date": s.updated_at.isoformat() if s.updated_at else "",
                    })
                    continue
                # Match by topic in result metadata
                result_str = str(ep.get("result", {})).lower()
                if topic_lower in result_str:
                    matched.append({
                        **ep,
                        "summary": s.summary[:200],
                        "date": s.updated_at.isoformat() if s.updated_at else "",
                    })

        return matched[:limit]
    except Exception as e:
        logger.debug("Episode search failed: %s", e)
        return []


async def get_recent_episodes(
    user_id: str,
    limit: int = MAX_EPISODE_CONTEXT,
) -> list[dict[str, Any]]:
    """Get most recent episodes for a user (regardless of topic)."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(SessionSummary)
                .where(
                    SessionSummary.user_id == uuid.UUID(user_id),
                    SessionSummary.episode_metadata.isnot(None),
                )
                .order_by(SessionSummary.updated_at.desc())
                .limit(10)
            )
            summaries = list(result.scalars().all())

        episodes: list[dict[str, Any]] = []
        for s in summaries:
            meta = s.episode_metadata or {}
            for ep in meta.get("episodes", []):
                episodes.append({
                    **ep,
                    "summary": s.summary[:200],
                    "date": s.updated_at.isoformat() if s.updated_at else "",
                })
                if len(episodes) >= limit:
                    return episodes

        return episodes
    except Exception as e:
        logger.debug("Recent episodes load failed: %s", e)
        return []


async def extract_episode_metadata(summary_text: str) -> dict[str, Any]:
    """Extract structured episode metadata from a dialog summary using LLM."""
    import json

    try:
        from src.core.llm.clients import google_client

        client = google_client()
        prompt = EPISODE_EXTRACTION_PROMPT.format(summary=summary_text)
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        text = (response.text or "").strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
        return json.loads(text)
    except Exception as e:
        logger.debug("Episode metadata extraction failed: %s", e)
        return {}


def format_episodes_block(episodes: list[dict[str, Any]]) -> str:
    """Format episodes as a context block for LLM injection."""
    if not episodes:
        return ""
    lines: list[str] = []
    for ep in episodes[:MAX_EPISODE_CONTEXT]:
        intent = ep.get("intent", "unknown")
        date = ep.get("date", "")[:10]
        result = ep.get("result", {})
        summary = ep.get("summary", "")
        parts = [f"[{date}] {intent}"]
        if result:
            # Show key result params (style, format, etc.)
            params = ", ".join(f"{k}={v}" for k, v in list(result.items())[:5])
            if params:
                parts.append(f"  params: {params}")
        if summary:
            parts.append(f"  context: {summary[:100]}")
        lines.append("\n".join(parts))
    return (
        "\n\n<past_episodes>\n"
        + "\n---\n".join(lines)
        + "\n</past_episodes>"
    )
