"""Life-tracking cron tasks: weekly digest, morning reminder, evening reflection."""

import logging
from datetime import date, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.core.life_helpers import get_communication_mode, query_life_events
from src.core.models.enums import LifeEventType
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


async def _get_family_users() -> list[tuple[str, str, int]]:
    """Get (family_id, user_id, telegram_id) for all users."""
    async with async_session() as session:
        result = await session.execute(select(User.family_id, User.id, User.telegram_id))
        return [(str(r[0]), str(r[1]), r[2]) for r in result.all()]


async def _send_telegram_message(telegram_id: int, text: str) -> None:
    """Send a message via Telegram Bot API."""
    from src.core.config import settings

    try:
        from aiogram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception as e:
        logger.error("Failed to send Telegram message to %s: %s", telegram_id, e)


@broker.task(schedule=[{"cron": "0 20 * * 0"}])  # Sunday 20:00
async def weekly_life_digest() -> None:
    """Generate and send a weekly life digest for all users."""
    today = date.today()
    week_ago = today - timedelta(days=7)

    users = await _get_family_users()

    for family_id, user_id, telegram_id in users:
        try:
            events = await query_life_events(
                family_id=family_id,
                user_id=user_id,
                date_from=week_ago,
                date_to=today,
                limit=100,
            )

            if not events:
                continue

            # Count events by type
            type_counts: dict[str, int] = {}
            for ev in events:
                t = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
                type_counts[t] = type_counts.get(t, 0) + 1

            # Build digest with Claude Sonnet
            summary_parts = [
                "<b>Еженедельный дайджест</b>",
                f"Период: {week_ago.strftime('%d.%m')} — {today.strftime('%d.%m.%Y')}",
                f"Записей: {len(events)}",
                "",
            ]

            type_icons = {
                "note": "\U0001f4dd",
                "food": "\U0001f37d",
                "drink": "\u2615",
                "mood": "\U0001f60a",
                "task": "\u2705",
                "reflection": "\U0001f319",
            }

            for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                icon = type_icons.get(t, "\U0001f4cc")
                summary_parts.append(f"  {icon} {t}: {count}")

            # Mood analysis if available
            mood_events = [e for e in events if e.type == LifeEventType.mood]
            if mood_events:
                mood_values = []
                for me in mood_events:
                    if me.data and isinstance(me.data, dict):
                        m = me.data.get("mood")
                        if m is not None:
                            mood_values.append(int(m))
                if mood_values:
                    avg_mood = sum(mood_values) / len(mood_values)
                    summary_parts.append(f"\n\U0001f4ca Средний mood: {avg_mood:.1f}/10")

            # Task completion
            task_events = [e for e in events if e.type == LifeEventType.task]
            if task_events:
                done = sum(
                    1
                    for te in task_events
                    if te.data and isinstance(te.data, dict) and te.data.get("done")
                )
                summary_parts.append(f"\u2705 Задачи: {done}/{len(task_events)} выполнено")

            # AI analysis via Claude Sonnet
            try:
                analysis = await _generate_digest_analysis(events)
                if analysis:
                    summary_parts.append(f"\n\U0001f4a1 <b>Инсайты:</b>\n{analysis}")
            except Exception as e:
                logger.warning("Digest analysis failed: %s", e)

            digest_text = "\n".join(summary_parts)
            await _send_telegram_message(telegram_id, digest_text)

            # Store digest in Mem0
            try:
                from src.core.memory.mem0_client import add_memory

                await add_memory(
                    content=digest_text,
                    user_id=user_id,
                    metadata={"type": "weekly_digest", "category": "life_digest"},
                )
            except Exception as e:
                logger.warning("Mem0 digest storage failed: %s", e)

            logger.info("Weekly digest sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Weekly digest failed for user %s: %s", user_id, e)


async def _generate_digest_analysis(events: list) -> str:
    """Generate AI analysis of weekly life events using Claude Sonnet."""
    from src.core.llm.clients import anthropic_client

    events_text = "\n".join(f"- [{e.type.value}] {e.date}: {e.text or ''}" for e in events[:50])

    client = anthropic_client()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=(
            "Ты анализируешь данные life-tracking за неделю. "
            "Дай 2-3 коротких инсайта: паттерны, тренды, рекомендации. "
            "Формат: bullet points. Русский язык. Без вступлений."
        ),
        messages=[{"role": "user", "content": events_text}],
    )
    return response.content[0].text.strip()


@broker.task(schedule=[{"cron": "0 8 * * *"}])  # Daily 08:00
async def morning_plan_reminder() -> None:
    """Remind users who haven't created a day plan yet."""
    today = date.today()
    users = await _get_family_users()

    for family_id, user_id, telegram_id in users:
        try:
            # Check if user has a day plan for today
            today_plans = await query_life_events(
                family_id=family_id,
                user_id=user_id,
                event_type=LifeEventType.task,
                date_from=today,
                date_to=today,
                limit=1,
            )

            if today_plans:
                continue  # Already has a plan

            # Check communication mode — don't remind silent users
            mode = await get_communication_mode(user_id)
            if mode == "silent":
                continue

            await _send_telegram_message(
                telegram_id,
                "\u2600\ufe0f <b>Доброе утро!</b>\n"
                "У вас пока нет плана на сегодня.\n"
                "Напишите задачи, и я сохраню их как план дня.",
            )
            logger.info("Morning reminder sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Morning reminder failed for user %s: %s", user_id, e)


@broker.task(schedule=[{"cron": "30 21 * * *"}])  # Daily 21:30
async def evening_reflection_prompt() -> None:
    """Prompt users who haven't done their daily reflection."""
    today = date.today()
    users = await _get_family_users()

    for family_id, user_id, telegram_id in users:
        try:
            # Check if user already reflected today
            reflections = await query_life_events(
                family_id=family_id,
                user_id=user_id,
                event_type=LifeEventType.reflection,
                date_from=today,
                date_to=today,
                limit=1,
            )

            if reflections:
                continue

            mode = await get_communication_mode(user_id)
            if mode == "silent":
                continue

            # Build a day summary to help reflection
            day_events = await query_life_events(
                family_id=family_id,
                user_id=user_id,
                date_from=today,
                date_to=today,
                limit=20,
            )

            summary = ""
            if day_events:
                summary = f"\n\nСегодня записано {len(day_events)} событий."
                task_events = [e for e in day_events if e.type == LifeEventType.task]
                if task_events:
                    summary += f"\n\u2705 Задачи: {len(task_events)}"

            await _send_telegram_message(
                telegram_id,
                f"\U0001f319 <b>Время для рефлексии</b>"
                f"{summary}\n\n"
                f"Что получилось сегодня? Что хотите улучшить?\n"
                f"Напишите свободным текстом.",
            )
            logger.info("Evening reflection prompt sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Evening reflection prompt failed for user %s: %s", user_id, e)
