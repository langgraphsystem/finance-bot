"""Quick capture skill — save a note with auto-tags and Mem0 indexing."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import (
    auto_tag,
    format_receipt,
    get_communication_mode,
    save_life_event,
)
from src.core.memory.mem0_client import add_memory
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

QUICK_CAPTURE_SYSTEM_PROMPT = """Ты помогаешь пользователю быстро записать мысль, заметку или идею.
Сохрани текст как есть, добавь теги автоматически."""


class QuickCaptureSkill:
    name = "quick_capture"
    intents = ["quick_capture"]
    model = "claude-haiku-4-5"

    @observe(name="quick_capture")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = intent_data.get("note") or intent_data.get("description") or message.text or ""

        if not text.strip():
            return SkillResult(response_text="Что записать? Отправьте текст заметки.")

        # Auto-tag in background (fast keyword tagger)
        tags = await auto_tag(text)

        event = await save_life_event(
            family_id=context.family_id,
            user_id=context.user_id,
            event_type=LifeEventType.note,
            text=text,
            tags=tags,
        )

        # Store in Mem0 for future semantic search (background task)
        async def _store_in_mem0():
            try:
                await add_memory(
                    content=text,
                    user_id=context.user_id,
                    metadata={"type": "note", "event_id": str(event.id), "tags": tags},
                )
            except Exception as e:
                logger.warning("Mem0 storage failed: %s", e)

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(
                response_text="",
                background_tasks=[_store_in_mem0],
            )
        elif mode == "coaching":
            tag_hint = f" [{', '.join(tags)}]" if tags else ""
            return SkillResult(
                response_text=format_receipt(LifeEventType.note, text, tags)
                + f"\n\U0001f4a1 Заметка сохранена{tag_hint}. Найти её можно через поиск.",
                background_tasks=[_store_in_mem0],
            )
        else:
            return SkillResult(
                response_text=format_receipt(LifeEventType.note, text, tags),
                background_tasks=[_store_in_mem0],
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return QUICK_CAPTURE_SYSTEM_PROMPT


skill = QuickCaptureSkill()
