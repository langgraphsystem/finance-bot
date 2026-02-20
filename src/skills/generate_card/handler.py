"""Generate visual card skill — LLM-designed HTML rendered to PNG."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


class GenerateCardSkill:
    name = "generate_card"
    intents = ["generate_card"]
    model = "claude-sonnet-4-6"

    @observe(name="generate_card")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.core.visual_cards import generate_card_html, html_to_png

        topic = intent_data.get("card_topic") or message.text or ""
        if not topic.strip():
            return SkillResult(
                response_text=(
                    "Опишите, какую карточку создать. Например:\n"
                    "• «трекер чтения на 30 дней»\n"
                    "• «список покупок на неделю»\n"
                    "• «привычки на февраль»"
                ),
            )

        html = await generate_card_html(topic)
        png_bytes = html_to_png(html)

        return SkillResult(response_text="", photo_bytes=png_bytes)

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Ты генерируешь визуальные карточки по запросу пользователя."


skill = GenerateCardSkill()
