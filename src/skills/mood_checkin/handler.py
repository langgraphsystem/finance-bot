"""Mood check-in skill — track mood, energy, stress, and sleep."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    format_receipt,
    get_communication_mode,
    save_life_event,
)
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MOOD_CHECKIN_SYSTEM_PROMPT = """Ты помогаешь пользователю оценить своё состояние.
Параметры: mood (настроение), energy (энергия), stress (стресс), sleep (сон).
Каждый параметр — число от 1 до 10."""


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
        sleep = intent_data.get("sleep")

        # If no metrics provided at all, return interactive buttons
        if not any([mood, energy, stress, sleep]):
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
        if sleep is not None:
            data["sleep"] = max(1, min(10, int(sleep)))
            parts.append(f"сон: {data['sleep']}/10")

        summary = ", ".join(parts)

        await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.mood,
            text=summary,
            data=data,
        )

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            avg = sum(data.values()) / len(data) if data else 0
            tip = (
                "Отличный день! Так держать."
                if avg >= 7
                else "Средний день — это нормально. Отдохните вечером."
                if avg >= 4
                else "Непростой день. Попробуйте прогулку или дыхательные упражнения."
            )
            return SkillResult(
                response_text=format_receipt(LifeEventType.mood, summary, None)
                + f"\n\U0001f4a1 {tip}"
            )
        else:
            return SkillResult(
                response_text=format_receipt(LifeEventType.mood, summary, None)
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return MOOD_CHECKIN_SYSTEM_PROMPT


skill = MoodCheckinSkill()
