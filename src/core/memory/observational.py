"""Observational Memory — Observer + Reflector (Phase 3.1).

Observer: Triggered when conversation history exceeds token threshold.
Compresses old messages into dated behavioral observations (5-40x compression).
Example: "[2026-03-01] Spends ~500₽ weekly on gas at Lukoil"

Reflector: Restructures observation log when it grows beyond threshold.
Removes outdated observations, merges similar ones.
"""

import logging
from datetime import UTC, datetime

from src.core.observability import observe

logger = logging.getLogger(__name__)

# Token thresholds
OBSERVER_TOKEN_THRESHOLD = 25_000  # Trigger observation extraction
REFLECTOR_TOKEN_THRESHOLD = 30_000  # Trigger observation restructuring
MAX_STORED_OBSERVATIONS = 50  # Cap stored observations per user

# Intents that benefit from behavioral observations in context
OBSERVATION_INTENTS: frozenset[str] = frozenset({
    "complex_query",
    "financial_summary",
    "cash_flow_forecast",
    "query_report",
    "morning_brief",
    "evening_recap",
    "day_plan",
    "day_reflection",
})

OBSERVER_PROMPT = """Проанализируй сообщения пользователя и извлеки поведенческие наблюдения.

СООБЩЕНИЯ:
{messages}

ПРАВИЛА:
1. Каждое наблюдение — датированный факт о поведении пользователя
2. Формат: [YYYY-MM-DD] Наблюдение
3. Фокус: паттерны трат, привычки, режим дня, предпочтения
4. Объедини повторяющиеся действия в паттерны
5. Сохраняй точные суммы и названия
6. Максимум 10 наблюдений
7. Игнорируй технические сообщения бота

Примеры:
- [2026-03-01] Тратит ~500₽ в неделю на бензин (Лукойл)
- [2026-03-01] Обычно делает покупки вечером (18:00-21:00)
- [2026-02-28] Отслеживает кофе ежедневно, 2-3 чашки
- [2026-02-27] Предпочитает краткие ответы без эмодзи

НАБЛЮДЕНИЯ:"""

REFLECTOR_PROMPT = """Реструктурируй лог наблюдений о пользователе.

ТЕКУЩИЕ НАБЛЮДЕНИЯ:
{observations}

ПРАВИЛА:
1. Удали устаревшие наблюдения (заменённые более новыми)
2. Объедини похожие наблюдения в одно
3. Сохрани самую свежую дату для каждого паттерна
4. Удали одноразовые события старше 30 дней
5. Приоритет: финансовые паттерны > привычки > разовые события
6. Максимум 20 наблюдений
7. Формат: [YYYY-MM-DD] Наблюдение

ОБНОВЛЁННЫЕ НАБЛЮДЕНИЯ:"""


def estimate_tokens(text: str) -> int:
    """Rough token count (1 token ~ 4 chars for Russian/English mix)."""
    return len(text) // 4 + 1


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    """Estimate total tokens across a list of messages."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


def should_observe(messages: list[dict[str, str]]) -> bool:
    """Check if Observer should trigger (token threshold exceeded)."""
    return estimate_message_tokens(messages) > OBSERVER_TOKEN_THRESHOLD


@observe(name="observer_extract")
async def extract_observations(
    messages: list[dict[str, str]],
    existing_observations: list[str] | None = None,
) -> list[str]:
    """Extract dated behavioral observations from conversation messages.

    Returns merged list: existing observations + newly extracted ones.
    Uses Gemini Flash for cheap, fast extraction.
    """
    if not messages:
        return existing_observations or []

    from src.core.llm.clients import google_client

    messages_text = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}"
        for m in messages
        if m.get("content")
    )
    if not messages_text.strip():
        return existing_observations or []

    try:
        client = google_client()
        prompt = OBSERVER_PROMPT.format(messages=messages_text)
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        new_obs = _parse_observations(response.text or "")
        return (existing_observations or []) + new_obs
    except Exception as e:
        logger.warning("Observer extraction failed: %s", e)
        return existing_observations or []


@observe(name="reflector_restructure")
async def restructure_observations(observations: list[str]) -> list[str]:
    """Restructure observation log when it grows too large.

    Removes outdated, merges similar, keeps most relevant (max 20).
    Only triggers when accumulated observations exceed token threshold.
    """
    if not observations:
        return []

    total_tokens = sum(estimate_tokens(o) for o in observations)
    if total_tokens < REFLECTOR_TOKEN_THRESHOLD:
        return observations

    from src.core.llm.clients import google_client

    try:
        client = google_client()
        obs_text = "\n".join(observations)
        prompt = REFLECTOR_PROMPT.format(observations=obs_text)
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        result = _parse_observations(response.text or "")
        return result or observations
    except Exception as e:
        logger.warning("Reflector restructure failed: %s", e)
        return observations


def _parse_observations(text: str) -> list[str]:
    """Parse LLM output into dated observation strings."""
    observations: list[str] = []
    for line in text.strip().split("\n"):
        line = line.strip().lstrip("- ").strip()
        if not line:
            continue
        if line.startswith("["):
            observations.append(line)
        elif len(line) > 10:
            # Add today's date if format is missing
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            observations.append(f"[{today}] {line}")
    return observations


def format_observations_block(observations: list[str]) -> str:
    """Format observations as a context block for LLM injection."""
    if not observations:
        return ""
    lines = "\n".join(f"- {obs}" for obs in observations[:20])
    return f"\n\n<behavioral_patterns>\n{lines}\n</behavioral_patterns>"


async def load_user_observations(user_id: str) -> list[str]:
    """Load observations from UserProfile.learned_patterns["observations"]."""
    import uuid

    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.models.user_profile import UserProfile

    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile.learned_patterns).where(
                    UserProfile.user_id == uuid.UUID(user_id)
                )
            )
            patterns = result.scalar_one_or_none()
            if patterns and isinstance(patterns, dict):
                return patterns.get("observations", [])
    except Exception as e:
        logger.debug("Load observations failed: %s", e)
    return []


async def save_user_observations(user_id: str, observations: list[str]) -> None:
    """Save observations to UserProfile.learned_patterns["observations"]."""
    import uuid

    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.models.user_profile import UserProfile

    try:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(
                    UserProfile.user_id == uuid.UUID(user_id)
                )
            )
            profile = result.scalar_one_or_none()
            if profile:
                patterns = profile.learned_patterns or {}
                patterns["observations"] = observations[-MAX_STORED_OBSERVATIONS:]
                profile.learned_patterns = patterns
                await session.commit()
    except Exception as e:
        logger.debug("Save observations failed: %s", e)
