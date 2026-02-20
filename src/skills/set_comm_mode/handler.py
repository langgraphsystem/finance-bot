"""Set communication mode skill — switches between silent, receipt, coaching."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import set_communication_mode
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SET_COMM_MODE_SYSTEM_PROMPT = """Ты помогаешь пользователю выбрать режим общения:
- silent (тихий): AI Assistant записывает молча, без ответа
- receipt (квитанция): краткое подтверждение-чек
- coaching (коучинг): подтверждение + короткий совет/инсайт"""

# Mapping of user-friendly terms to canonical mode names
MODE_ALIASES: dict[str, str] = {
    "тихий": "silent",
    "тихо": "silent",
    "молча": "silent",
    "silent": "silent",
    "молчание": "silent",
    "без ответа": "silent",
    "квитанция": "receipt",
    "чек": "receipt",
    "receipt": "receipt",
    "кратко": "receipt",
    "default": "receipt",
    "обычный": "receipt",
    "коучинг": "coaching",
    "coaching": "coaching",
    "coach": "coaching",
    "совет": "coaching",
    "советы": "coaching",
    "инсайт": "coaching",
}

MODE_DESCRIPTIONS: dict[str, str] = {
    "silent": "<b>Тихий режим</b>\nБот записывает всё молча, без подтверждений.",
    "receipt": "<b>Режим квитанции</b>\nКраткое подтверждение после каждой записи.",
    "coaching": "<b>Режим коучинга</b>\nПодтверждение + короткий инсайт или совет.",
}


class SetCommModeSkill:
    name = "set_comm_mode"
    intents = ["set_comm_mode"]
    model = "gpt-5.2"

    @observe(name="set_comm_mode")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = (message.text or "").lower().strip()

        # Try intent_data first
        mode = intent_data.get("comm_mode") or intent_data.get("mode")

        # Fallback: scan message text for aliases
        if not mode:
            for alias, canonical in MODE_ALIASES.items():
                if alias in text:
                    mode = canonical
                    break

        if not mode or mode not in ("silent", "receipt", "coaching"):
            return SkillResult(
                response_text="Выберите режим общения:",
                buttons=[
                    {"text": "\U0001f910 Тихий", "callback": "comm_mode:silent"},
                    {"text": "\U0001f4cb Квитанция", "callback": "comm_mode:receipt"},
                    {"text": "\U0001f4a1 Коучинг", "callback": "comm_mode:coaching"},
                ],
            )

        await set_communication_mode(context.user_id, mode)

        description = MODE_DESCRIPTIONS.get(mode, f"Режим: {mode}")
        return SkillResult(response_text=f"Готово! {description}")

    def get_system_prompt(self, context: SessionContext) -> str:
        return SET_COMM_MODE_SYSTEM_PROMPT


skill = SetCommModeSkill()
