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

# ---- i18n texts for cron messages -------------------------------------------

_TEXTS = {
    "en": {
        "weekly_title": "Weekly Digest",
        "weekly_period": "Period",
        "weekly_entries": "Entries",
        "weekly_avg_mood": "Average mood",
        "weekly_tasks": "Tasks: {done}/{total} completed",
        "weekly_insights": "Insights",
        "morning_title": "\u2600\ufe0f <b>Good morning!</b>",
        "morning_body": (
            "You don't have a day plan yet.\nWrite your tasks and I'll save them as your plan."
        ),
        "evening_title": "\U0001f319 <b>Time to reflect</b>",
        "evening_body": (
            "What went well today? What would you like to improve?\nJust write freely."
        ),
        "evening_logged": "Logged {n} events today.",
        "evening_tasks": "\u2705 Tasks: {n}",
        "digest_system": (
            "You analyze weekly life-tracking data. "
            "Give 2-3 short insights: patterns, trends, recommendations. "
            "Format: bullet points. English. No preamble."
        ),
    },
    "es": {
        "weekly_title": "Resumen semanal",
        "weekly_period": "Periodo",
        "weekly_entries": "Registros",
        "weekly_avg_mood": "\u00c1nimo promedio",
        "weekly_tasks": "Tareas: {done}/{total} completadas",
        "weekly_insights": "Ideas",
        "morning_title": "\u2600\ufe0f <b>\u00a1Buenos d\u00edas!</b>",
        "morning_body": (
            "A\u00fan no tienes un plan para hoy.\n"
            "Escribe tus tareas y las guardar\u00e9 como tu plan del d\u00eda."
        ),
        "evening_title": "\U0001f319 <b>Hora de reflexionar</b>",
        "evening_body": (
            "\u00bfQu\u00e9 sali\u00f3 bien hoy? "
            "\u00bfQu\u00e9 te gustar\u00eda mejorar?\n"
            "Escribe libremente."
        ),
        "evening_logged": "Registraste {n} eventos hoy.",
        "evening_tasks": "\u2705 Tareas: {n}",
        "digest_system": (
            "Analizas datos de life-tracking de la semana. "
            "Da 2-3 ideas cortas: patrones, tendencias, recomendaciones. "
            "Formato: vi\u00f1etas. Espa\u00f1ol. Sin introducci\u00f3n."
        ),
    },
    "zh": {
        "weekly_title": "\u6bcf\u5468\u603b\u7ed3",
        "weekly_period": "\u65f6\u95f4\u6bb5",
        "weekly_entries": "\u8bb0\u5f55",
        "weekly_avg_mood": "\u5e73\u5747\u5fc3\u60c5",
        "weekly_tasks": "\u4efb\u52a1\uff1a{done}/{total} \u5df2\u5b8c\u6210",
        "weekly_insights": "\u6d1e\u5bdf",
        "morning_title": "\u2600\ufe0f <b>\u65e9\u4e0a\u597d\uff01</b>",
        "morning_body": (
            "\u4f60\u8fd8\u6ca1\u6709\u4eca\u5929\u7684\u8ba1\u5212\u3002\n"
            "\u5199\u4e0b\u4f60\u7684\u4efb\u52a1\uff0c"
            "\u6211\u4f1a\u4fdd\u5b58\u4e3a\u4eca\u65e5\u8ba1\u5212\u3002"
        ),
        "evening_title": "\U0001f319 <b>\u53cd\u601d\u65f6\u95f4</b>",
        "evening_body": (
            "\u4eca\u5929\u4ec0\u4e48\u505a\u5f97\u597d\uff1f"
            "\u54ea\u4e9b\u53ef\u4ee5\u6539\u8fdb\uff1f\n"
            "\u968f\u4fbf\u5199\u5199\u3002"
        ),
        "evening_logged": "\u4eca\u5929\u8bb0\u5f55\u4e86 {n} \u4e2a\u4e8b\u4ef6\u3002",
        "evening_tasks": "\u2705 \u4efb\u52a1\uff1a{n}",
        "digest_system": (
            "\u4f60\u5206\u6790\u6bcf\u5468\u751f\u6d3b\u8ddf\u8e2a\u6570\u636e\u3002"
            "\u7ed9\u51fa2-3\u4e2a\u7b80\u77ed\u6d1e\u5bdf\uff1a"
            "\u6a21\u5f0f\u3001\u8d8b\u52bf\u3001\u5efa\u8bae\u3002"
            "\u683c\u5f0f\uff1a\u8981\u70b9\u3002\u4e2d\u6587\u3002\u65e0\u5f00\u573a\u767d\u3002"
        ),
    },
    "ru": {  # noqa: E501
        "weekly_title": "Еженедельный дайджест",
        "weekly_period": "Период",
        "weekly_entries": "Записей",
        "weekly_avg_mood": "Средний mood",
        "weekly_tasks": "Задачи: {done}/{total} выполнено",
        "weekly_insights": "Инсайты",
        "morning_title": "☀️ <b>Доброе утро!</b>",
        "morning_body": (
            "У вас пока нет плана на сегодня.\n"
            "Напишите задачи, и я сохраню их как план дня."
        ),
        "evening_title": "\U0001f319 <b>Время для рефлексии</b>",
        "evening_body": "Что получилось сегодня? Что хотите улучшить?\nНапишите свободным текстом.",
        "evening_logged": "Сегодня записано {n} событий.",
        "evening_tasks": "✅ Задачи: {n}",
        "digest_system": (
            "Ты анализируешь данные life-tracking за неделю. "
            "Дай 2-3 коротких инсайта: паттерны, тренды, рекомендации. "
            "Формат: bullet points. Русский язык. Без вступлений."
        ),
    },
}


def _t(lang: str) -> dict[str, str]:
    """Get texts for a language, defaulting to English."""
    return _TEXTS.get(lang, _TEXTS["en"])


async def _get_family_users() -> list[tuple[str, str, int, str]]:
    """Get (family_id, user_id, telegram_id, language) for all users."""
    async with async_session() as session:
        result = await session.execute(
            select(User.family_id, User.id, User.telegram_id, User.language)
        )
        return [(str(r[0]), str(r[1]), r[2], r[3] or "en") for r in result.all()]


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

    for family_id, user_id, telegram_id, lang in users:
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

            t = _t(lang)

            # Count events by type
            type_counts: dict[str, int] = {}
            for ev in events:
                tp = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
                type_counts[tp] = type_counts.get(tp, 0) + 1

            # Build digest
            summary_parts = [
                f"<b>{t['weekly_title']}</b>",
                f"{t['weekly_period']}: {week_ago.strftime('%d.%m')}"
                f" — {today.strftime('%d.%m.%Y')}",
                f"{t['weekly_entries']}: {len(events)}",
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
                    summary_parts.append(f"\n\U0001f4ca {t['weekly_avg_mood']}: {avg_mood:.1f}/10")

            # Task completion
            task_events = [e for e in events if e.type == LifeEventType.task]
            if task_events:
                done = sum(
                    1
                    for te in task_events
                    if te.data and isinstance(te.data, dict) and te.data.get("done")
                )
                summary_parts.append(
                    f"\u2705 {t['weekly_tasks'].format(done=done, total=len(task_events))}"
                )

            # AI analysis via Claude Sonnet
            try:
                analysis = await _generate_digest_analysis(events, lang)
                if analysis:
                    summary_parts.append(f"\n\U0001f4a1 <b>{t['weekly_insights']}:</b>\n{analysis}")
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


async def _generate_digest_analysis(events: list, lang: str = "en") -> str:
    """Generate AI analysis of weekly life events using Claude Sonnet."""
    from src.core.llm.clients import anthropic_client

    events_text = "\n".join(f"- [{e.type.value}] {e.date}: {e.text or ''}" for e in events[:50])

    client = anthropic_client()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=_t(lang)["digest_system"],
        messages=[{"role": "user", "content": events_text}],
    )
    return response.content[0].text.strip()


@broker.task(schedule=[{"cron": "0 8 * * *"}])  # Daily 08:00
async def morning_plan_reminder() -> None:
    """Remind users who haven't created a day plan yet."""
    today = date.today()
    users = await _get_family_users()

    for family_id, user_id, telegram_id, lang in users:
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

            t = _t(lang)
            await _send_telegram_message(
                telegram_id,
                f"{t['morning_title']}\n{t['morning_body']}",
            )
            logger.info("Morning reminder sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Morning reminder failed for user %s: %s", user_id, e)


@broker.task(schedule=[{"cron": "30 21 * * *"}])  # Daily 21:30
async def evening_reflection_prompt() -> None:
    """Prompt users who haven't done their daily reflection."""
    today = date.today()
    users = await _get_family_users()

    for family_id, user_id, telegram_id, lang in users:
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

            t = _t(lang)

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
                summary = f"\n\n{t['evening_logged'].format(n=len(day_events))}"
                task_events = [e for e in day_events if e.type == LifeEventType.task]
                if task_events:
                    summary += f"\n{t['evening_tasks'].format(n=len(task_events))}"

            await _send_telegram_message(
                telegram_id,
                f"{t['evening_title']}{summary}\n\n{t['evening_body']}",
            )
            logger.info("Evening reflection prompt sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Evening reflection prompt failed for user %s: %s", user_id, e)
