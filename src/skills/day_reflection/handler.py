"""Day reflection skill — end-of-day review and journaling."""

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

DAY_REFLECTION_SYSTEM_PROMPT = """Ты помогаешь пользователю подвести итоги дня.
Если пользователь написал рефлексию, сохрани её.
Если просто попросил "рефлексия" без деталей, задай наводящий вопрос."""

# Trigger words that indicate the user wants to start a reflection
# but hasn't provided actual content yet
BARE_TRIGGERS = {
    "рефлексия",
    "reflection",
    "итоги дня",
    "итоги",
    "подвести итоги",
    "дневник",
}


class DayReflectionSkill:
    name = "day_reflection"
    intents = ["day_reflection"]
    model = "claude-haiku-4-5"

    @observe(name="day_reflection")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = intent_data.get("reflection") or intent_data.get("description") or message.text or ""
        text_stripped = text.strip()

        # If the message is just a bare trigger word, ask a guiding question
        if text_stripped.lower() in BARE_TRIGGERS or not text_stripped:
            return SkillResult(
                response_text=(
                    "<b>Рефлексия дня</b>\n\n"
                    "Что получилось сегодня? Что можно улучшить?\n"
                    "Напишите свободным текстом."
                ),
            )

        # Save the reflection
        await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.reflection,
            text=text_stripped,
        )

        mode = await get_communication_mode(context.user_id)
        response = format_save_response(LifeEventType.reflection, text_stripped)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            return SkillResult(
                response_text=response
                + "\n\U0001f4a1 Регулярная рефлексия улучшает осознанность и продуктивность."
            )
        else:
            return SkillResult(response_text=response)

    def get_system_prompt(self, context: SessionContext) -> str:
        return DAY_REFLECTION_SYSTEM_PROMPT


skill = DayReflectionSkill()
