"""Track food skill — logs meals and food intake."""

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

TRACK_FOOD_SYSTEM_PROMPT = """Ты помогаешь пользователю записать приём пищи.
Извлеки из сообщения: блюдо (food_item), тип приёма (meal_type: breakfast/lunch/dinner/snack).
Если meal_type не указан, определи по времени или контексту."""

MEAL_TYPE_ALIASES: dict[str, str] = {
    "завтрак": "breakfast",
    "breakfast": "breakfast",
    "утро": "breakfast",
    "обед": "lunch",
    "lunch": "lunch",
    "ужин": "dinner",
    "dinner": "dinner",
    "вечер": "dinner",
    "перекус": "snack",
    "snack": "snack",
    "полдник": "snack",
}


class TrackFoodSkill:
    name = "track_food"
    intents = ["track_food"]
    model = "claude-haiku-4-5"

    @observe(name="track_food")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = message.text or ""
        text_lower = text.lower()

        food_item = intent_data.get("food_item") or intent_data.get("food") or text.strip()
        meal_type = intent_data.get("meal_type") or intent_data.get("meal")

        if not food_item or not food_item.strip():
            return SkillResult(
                response_text="Что вы ели? Напишите, например: «овсянка на завтрак».",
            )

        # Resolve meal_type from aliases if not provided
        if not meal_type:
            for alias, canonical in MEAL_TYPE_ALIASES.items():
                if alias in text_lower:
                    meal_type = canonical
                    break
            if not meal_type:
                meal_type = "meal"

        data = {"food_item": food_item, "meal_type": meal_type}

        await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.food,
            text=f"{meal_type}: {food_item}",
            data=data,
        )

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            return SkillResult(
                response_text=format_receipt(LifeEventType.food, f"{meal_type}: {food_item}", None)
                + "\n\U0001f4a1 Регулярное отслеживание питания помогает замечать паттерны."
            )
        else:
            return SkillResult(
                response_text=format_receipt(LifeEventType.food, f"{meal_type}: {food_item}", None)
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return TRACK_FOOD_SYSTEM_PROMPT


skill = TrackFoodSkill()
