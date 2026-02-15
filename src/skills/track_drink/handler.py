"""Track drink skill — logs coffee, tea, water, and other beverages."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    format_receipt,
    get_communication_mode,
    save_life_event,
)
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Keyword-based drink detection (fast path, no LLM needed)
DRINK_KEYWORDS: dict[str, str] = {
    "кофе": "coffee",
    "coffee": "coffee",
    "эспрессо": "coffee",
    "espresso": "coffee",
    "латте": "coffee",
    "latte": "coffee",
    "капучино": "coffee",
    "cappuccino": "coffee",
    "американо": "coffee",
    "americano": "coffee",
    "чай": "tea",
    "tea": "tea",
    "зелёный чай": "tea",
    "зеленый чай": "tea",
    "вода": "water",
    "water": "water",
    "сок": "juice",
    "juice": "juice",
    "смузи": "smoothie",
    "smoothie": "smoothie",
}

TRACK_DRINK_SYSTEM_PROMPT = """Ты помогаешь трекать напитки пользователя.
Извлеки из сообщения: название напитка (item), объём в мл (volume_ml), количество (count).
Ответь ТОЛЬКО JSON: {"item": "coffee", "volume_ml": 250, "count": 1}
Если объём не указан, используй стандартный: coffee=250, tea=200, water=330.
Если количество не указано, count=1."""


class TrackDrinkSkill:
    name = "track_drink"
    intents = ["track_drink"]
    model = "claude-haiku-4-5"

    @observe(name="track_drink")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = message.text or ""
        text_lower = text.lower()

        # Fast path: keyword matching
        item = intent_data.get("item")
        volume_ml = intent_data.get("volume_ml")
        count = intent_data.get("count", 1)

        if not item:
            for keyword, drink_name in DRINK_KEYWORDS.items():
                if keyword in text_lower:
                    item = drink_name
                    break

        # LLM fallback for ambiguous input
        if not item:
            try:
                import json

                client = anthropic_client()
                prompt_data = PromptAdapter.for_claude(
                    system=TRACK_DRINK_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": text}],
                )
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=128,
                    **prompt_data,
                )
                parsed = json.loads(response.content[0].text)
                item = parsed.get("item", "drink")
                volume_ml = parsed.get("volume_ml", volume_ml)
                count = parsed.get("count", count)
            except Exception:
                logger.warning("LLM drink extraction failed", exc_info=True)
                item = "drink"

        # Default volumes by drink type
        if not volume_ml:
            default_volumes = {"coffee": 250, "tea": 200, "water": 330}
            volume_ml = default_volumes.get(item, 250)

        count = count or 1

        data = {"item": item, "volume_ml": volume_ml, "count": count}

        await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.drink,
            text=f"{item} x{count}",
            data=data,
        )

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            return SkillResult(
                response_text=format_receipt(LifeEventType.drink, f"{item} x{count}", None)
                + f"\n\U0001f4a1 {volume_ml * count} мл за раз — отличный темп гидратации!"
            )
        else:
            return SkillResult(
                response_text=format_receipt(LifeEventType.drink, f"{item} x{count}", None)
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return TRACK_DRINK_SYSTEM_PROMPT


skill = TrackDrinkSkill()
