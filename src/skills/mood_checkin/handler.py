"""Mood check-in skill — track mood, energy, stress, and sleep."""

import logging
from datetime import date, timedelta
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    format_save_response,
    get_communication_mode,
    query_life_events,
    save_life_event,
)
from src.core.llm.clients import generate_text
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MOOD_CHECKIN_SYSTEM_PROMPT = """Ты помогаешь пользователю оценить своё состояние.
Параметры: mood (настроение), energy (энергия), stress (стресс) — шкала 1-10.
sleep_hours — количество часов сна (напр. 7.5)."""

COACHING_SYSTEM_PROMPT = """\
Ты помогаешь пользователю отрефлексировать своё состояние.
Тебе даны текущие показатели и тренд за последние дни (если есть).
Дай краткий, эмпатичный совет. Не ставь диагнозов.
Если тренд ухудшается — мягко предложи действие.
2-3 предложения. Используй HTML-теги для Telegram (<b>, <i>). Отвечай на языке пользователя."""


class MoodCheckinSkill:
    name = "mood_checkin"
    intents = ["mood_checkin"]
    model = "claude-sonnet-4-6"

    @observe(name="mood_checkin")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        mood = intent_data.get("mood")
        energy = intent_data.get("energy")
        stress = intent_data.get("stress")
        sleep_hours = intent_data.get("sleep_hours")

        # If no metrics provided at all, return interactive buttons
        if not any([mood, energy, stress, sleep_hours]):
            return SkillResult(
                response_text="Как дела? Оцените от 1 до 10:",
                buttons=[
                    *[
                        {"text": f"\U0001f60a {i}", "callback": f"mood_val:mood:{i}"}
                        for i in (3, 5, 7, 9)
                    ],
                    *[
                        {"text": f"\u26a1 {i}", "callback": f"mood_val:energy:{i}"}
                        for i in (3, 5, 7, 9)
                    ],
                ],
            )

        # Clamp values to 1-10
        data: dict[str, Any] = {}
        parts: list[str] = []

        if mood is not None:
            data["mood"] = max(1, min(10, int(mood)))
            parts.append(f"настроение: {data['mood']}/10")
        if energy is not None:
            data["energy"] = max(1, min(10, int(energy)))
            parts.append(f"энергия: {data['energy']}/10")
        if stress is not None:
            data["stress"] = max(1, min(10, int(stress)))
            parts.append(f"стресс: {data['stress']}/10")
        if sleep_hours is not None:
            data["sleep_hours"] = round(float(sleep_hours), 1)
            parts.append(f"сон: {data['sleep_hours']}ч")

        summary = ", ".join(parts)

        await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.mood,
            text=summary,
            data=data,
        )

        mode = await get_communication_mode(context.user_id)
        response = format_save_response(LifeEventType.mood, summary, data=data)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            try:
                trend = await _get_mood_trend(context.family_id, context.user_id)
                prompt_parts = [f"Текущие показатели: {summary}"]
                if trend:
                    prompt_parts.append(f"Тренд за последние дни:\n{trend}")
                tip = await generate_text(
                    model=self.model,
                    system=COACHING_SYSTEM_PROMPT,
                    prompt="\n".join(prompt_parts),
                    max_tokens=200,
                )
            except Exception:
                logger.exception("LLM coaching call failed for mood_checkin")
                tip = "\U0001f4a1 Следите за динамикой — это помогает понять себя лучше."
            return SkillResult(response_text=f"{response}\n{tip}")
        else:
            return SkillResult(response_text=response)

    def get_system_prompt(self, context: SessionContext) -> str:
        return MOOD_CHECKIN_SYSTEM_PROMPT


async def _get_mood_trend(family_id: str, user_id: str) -> str:
    """Build a short summary of mood events from the last 7 days."""
    events = await query_life_events(
        family_id=family_id,
        user_id=user_id,
        event_type=LifeEventType.mood,
        date_from=date.today() - timedelta(days=7),
        limit=14,
    )
    if not events:
        return ""
    lines: list[str] = []
    for e in events:
        d = e.data or {}
        parts = []
        if "mood" in d:
            parts.append(f"mood={d['mood']}")
        if "energy" in d:
            parts.append(f"energy={d['energy']}")
        if "stress" in d:
            parts.append(f"stress={d['stress']}")
        if parts:
            day = e.created_at.strftime("%d.%m") if e.created_at else "?"
            lines.append(f"{day}: {', '.join(parts)}")
    return "\n".join(lines)


skill = MoodCheckinSkill()
