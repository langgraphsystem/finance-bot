"""Mood check-in skill — track mood, energy, stress, and sleep."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    format_save_response,
    get_communication_mode,
    save_life_event,
)
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MOOD_CHECKIN_SYSTEM_PROMPT = """Ты помогаешь пользователю оценить своё состояние.
Параметры: mood (настроение), energy (энергия), stress (стресс) — шкала 1-10.
sleep_hours — количество часов сна (напр. 7.5)."""


class MoodCheckinSkill:
    name = "mood_checkin"
    intents = ["mood_checkin"]
    model = "claude-haiku-4-5"

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
            scale_vals = [v for k, v in data.items() if k != "sleep_hours"]
            avg = sum(scale_vals) / len(scale_vals) if scale_vals else 5
            tip = (
                "Отличный день! Так держать."
                if avg >= 7
                else "Средний день — это нормально. Отдохните вечером."
                if avg >= 4
                else "Непростой день. Попробуйте прогулку или дыхательные упражнения."
            )
            return SkillResult(response_text=response + f"\n\U0001f4a1 {tip}")
        else:
            return SkillResult(response_text=response)

    def get_system_prompt(self, context: SessionContext) -> str:
        return MOOD_CHECKIN_SYSTEM_PROMPT


skill = MoodCheckinSkill()
