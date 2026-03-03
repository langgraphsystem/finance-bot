"""Layer 5 — Incremental dialog summarization.

Triggers when message_count > 15. Uses Gemini 3 Flash for cheap, fast
summarization. Stores results in session_summaries table.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from src.core.db import async_session
from src.core.llm.clients import google_client
from src.core.models.conversation import ConversationMessage
from src.core.models.session_summary import SessionSummary
from src.core.observability import observe

logger = logging.getLogger(__name__)

FINANCIAL_SUMMARY_PROMPT = """
Обнови саммари диалога между пользователем и AI Assistant.
Это ИНКРЕМЕНТАЛЬНОЕ обновление — объедини с существующим саммари.

ТЕКУЩЕЕ САММАРИ:
{existing_summary}

НОВЫЕ СООБЩЕНИЯ:
{new_messages}

ПРАВИЛА:
1. НИКОГДА не удаляй финансовые цифры (суммы, проценты, даты)
2. НИКОГДА не удаляй названия категорий и бюджетные лимиты
3. Сохраняй ТОЧНЫЕ суммы ("50,000 RUB", НЕ "около 50к")
4. Структура:
   ## Финансовые данные
   - [суммы, даты, категории, упомянутые в диалоге]
   ## Предпочтения пользователя
   - [привычки трат, настройки уведомлений]
   ## Контекст диалога
   - [что обсуждали, принятые решения, открытые вопросы]
5. Если новые данные ПРОТИВОРЕЧАТ саммари — оставь НОВЫЕ,
   отметь изменение ("Бюджет продуктов обновлён с 30к до 40к")
6. Максимум 400 токенов

ОБНОВЛЁННОЕ САММАРИ:
"""

SUMMARY_THRESHOLD = 15  # Trigger summarization after 15 messages (fallback)
TOKEN_THRESHOLD = 25_000  # Primary trigger: token-based (Phase 3.1)


@observe(name="summarize_dialog")
async def summarize_dialog(user_id: str, family_id: str) -> str | None:
    """Create or update incremental dialog summary if message count > threshold."""
    try:
        async with async_session() as session:
            # Count recent messages
            count_result = await session.execute(
                select(func.count(ConversationMessage.id)).where(
                    ConversationMessage.user_id == uuid.UUID(user_id)
                )
            )
            msg_count = count_result.scalar() or 0

            if msg_count < SUMMARY_THRESHOLD:
                return None

            # Get existing summary
            sum_result = await session.execute(
                select(SessionSummary)
                .where(SessionSummary.user_id == uuid.UUID(user_id))
                .order_by(SessionSummary.updated_at.desc())
                .limit(1)
            )
            existing = sum_result.scalar_one_or_none()
            existing_text = existing.summary if existing else "Нет предыдущего саммари."
            last_count = existing.message_count if existing else 0

            # Skip if no new messages since last summary
            new_count = msg_count - last_count
            if new_count <= 0:
                return existing_text

            # Get new messages since last summary
            query = (
                select(ConversationMessage)
                .where(ConversationMessage.user_id == uuid.UUID(user_id))
                .order_by(ConversationMessage.created_at.desc())
                .limit(new_count)
            )
            msg_result = await session.execute(query)
            new_messages = msg_result.scalars().all()

            if not new_messages:
                return existing_text

            # Phase 3.1: Check token threshold for Observer trigger
            run_observer = False
            try:
                from src.core.memory.observational import (
                    OBSERVER_TOKEN_THRESHOLD,
                    estimate_tokens,
                )

                total_tokens = sum(
                    estimate_tokens(m.content or "") for m in new_messages
                )
                run_observer = total_tokens > OBSERVER_TOKEN_THRESHOLD
            except Exception as e:
                logger.debug("Token threshold check failed: %s", e)

            # Format messages for prompt (reverse to chronological order)
            messages_text = "\n".join(
                f"{m.role.value}: {m.content}" for m in reversed(list(new_messages))
            )

            # Call Gemini 3 Flash for summarization (Claude Haiku fallback on 429)
            prompt = FINANCIAL_SUMMARY_PROMPT.format(
                existing_summary=existing_text,
                new_messages=messages_text,
            )

            summary_text: str
            try:
                client = google_client()
                response = await client.aio.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=prompt,
                )
                summary_text = response.text
            except Exception as gemini_err:
                if "429" in str(gemini_err) or "RESOURCE_EXHAUSTED" in str(gemini_err):
                    logger.warning("Gemini rate limit hit, falling back to Claude Haiku")
                    from src.core.llm.clients import anthropic_client
                    haiku = anthropic_client()
                    haiku_resp = await haiku.messages.create(
                        model="claude-haiku-4-5",
                        max_tokens=512,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    summary_text = haiku_resp.content[0].text
                else:
                    raise

            # Save or update summary
            target_summary: SessionSummary
            if existing:
                existing.summary = summary_text
                existing.message_count = msg_count
                existing.token_count = len(summary_text.split())  # rough estimate
                existing.updated_at = datetime.now(UTC)
                target_summary = existing
            else:
                target_summary = SessionSummary(
                    user_id=uuid.UUID(user_id),
                    family_id=uuid.UUID(family_id),
                    session_id=uuid.uuid4(),
                    summary=summary_text,
                    message_count=msg_count,
                    token_count=len(summary_text.split()),
                )
                session.add(target_summary)

            # Phase 3.2: Extract episode metadata before commit (single txn)
            try:
                from src.core.memory.episodic import extract_episode_metadata

                episode_meta = await extract_episode_metadata(summary_text)
                if episode_meta:
                    meta = target_summary.episode_metadata or {}
                    meta["episode_info"] = episode_meta
                    target_summary.episode_metadata = meta
            except Exception as e:
                logger.debug("Episode metadata extraction failed: %s", e)

            await session.commit()

            # Phase 3.1: Run Observer alongside summarization
            if run_observer:
                try:
                    from src.core.memory.observational import (
                        extract_observations,
                        load_user_observations,
                        save_user_observations,
                    )

                    msg_dicts = [
                        {"role": m.role.value, "content": m.content or ""}
                        for m in reversed(list(new_messages))
                    ]
                    existing_obs = await load_user_observations(user_id)
                    updated_obs = await extract_observations(
                        msg_dicts, existing_obs
                    )
                    await save_user_observations(user_id, updated_obs)
                except Exception as e:
                    logger.debug("Observer alongside summarization failed: %s", e)

            return summary_text

    except Exception as e:
        logger.error("Dialog summarization failed: %s", e, exc_info=True)
        return None


async def get_session_summary(user_id: str) -> SessionSummary | None:
    """Retrieve the most recent session summary for a user."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(SessionSummary)
                .where(SessionSummary.user_id == uuid.UUID(user_id))
                .order_by(SessionSummary.updated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.warning("Failed to retrieve session summary: %s", e)
        return None
