"""Memory Vault — user-controlled memory management (show / forget / save / update)."""

import logging
from typing import Any

from src.core.observability import observe
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MEMORY_VAULT_SYSTEM_PROMPT = (
    "You help the user manage their stored memories. "
    "Be concise and clear when listing or confirming operations."
)

MAX_DISPLAY_MEMORIES = 20


register_strings("memory_vault", {"en": {}, "ru": {}, "es": {}})


class MemoryVaultSkill:
    name = "memory_vault"
    intents = ["memory_show", "memory_forget", "memory_save", "memory_update"]
    model = "gpt-5.4-2026-03-05"

    @observe(name="memory_vault")
    async def execute(
        self,
        message,
        context,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.core.memory.mem0_client import (
            add_memory,
            delete_all_memories,
            delete_memory,
            get_all_memories,
            search_memories,
        )

        intent = intent_data.get("_intent") or "memory_show"

        if intent == "memory_show":
            return await self._handle_show(context, get_all_memories)

        if intent == "memory_forget":
            query = intent_data.get("memory_query") or message.text or ""
            return await self._handle_forget(
                context, query, search_memories, delete_memory, delete_all_memories
            )

        if intent == "memory_save":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_save(context, content, add_memory)

        if intent == "memory_update":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_update(
                context, content, search_memories, delete_memory, add_memory
            )

        return SkillResult(response_text="Unknown memory action.")

    async def _handle_show(self, context, get_all_memories) -> SkillResult:
        memories = await get_all_memories(context.user_id)
        if not memories:
            return SkillResult(response_text="No stored memories yet.")

        lines = []
        for i, mem in enumerate(memories[:MAX_DISPLAY_MEMORIES], 1):
            text = mem.get("memory", mem.get("text", ""))
            if text:
                lines.append(f"{i}. {text}")

        if not lines:
            return SkillResult(response_text="No stored memories yet.")

        header = f"<b>Your memories ({len(memories)} total):</b>\n\n"
        body = "\n".join(lines)
        extra = ""
        if len(memories) > MAX_DISPLAY_MEMORIES:
            extra = f"\n\n... and {len(memories) - MAX_DISPLAY_MEMORIES} more."

        return SkillResult(
            response_text=header + body + extra,
            buttons=[
                {"text": "Clear all", "callback": "memory:clear_all"},
            ],
        )

    async def _handle_forget(
        self, context, query, search_memories, delete_memory, delete_all_memories
    ) -> SkillResult:
        query = query.strip()
        if not query:
            return SkillResult(response_text="What should I forget? Tell me what to remove.")

        # Check for "clear all" / "forget everything"
        lower = query.lower()
        if any(kw in lower for kw in ["all", "everything", "всё", "все", "todo"]):
            await delete_all_memories(context.user_id)
            return SkillResult(response_text="All memories cleared.")

        matches = await search_memories(query, context.user_id, limit=5)
        if not matches:
            return SkillResult(response_text=f"No memories found matching '{query}'.")

        deleted = 0
        for mem in matches:
            mem_id = mem.get("id")
            if mem_id:
                try:
                    await delete_memory(mem_id, context.user_id)
                    deleted += 1
                except Exception:
                    logger.warning("Failed to delete memory %s", mem_id, exc_info=True)

        if deleted:
            return SkillResult(
                response_text=f"Deleted {deleted} memory{'s' if deleted > 1 else ''} "
                f"matching '{query}'."
            )
        return SkillResult(response_text=f"Could not delete memories for '{query}'.")

    async def _handle_save(self, context, content, add_memory) -> SkillResult:
        content = content.strip()
        if not content:
            return SkillResult(response_text="What should I remember?")

        await add_memory(
            content=content,
            user_id=context.user_id,
            metadata={"type": "explicit", "source": "memory_vault"},
        )
        # Phase 11: Confirmation with saved content
        return SkillResult(
            response_text=f"Saved: <b>{content[:100]}</b>"
        )

    async def _handle_update(
        self, context, content, search_memories, delete_memory, add_memory
    ) -> SkillResult:
        """Phase 11: Update an existing memory fact."""
        content = content.strip()
        if not content:
            return SkillResult(response_text="What should I update?")

        # Search for existing fact
        matches = await search_memories(content, context.user_id, limit=3)
        if matches:
            # Delete the closest match, then add the new version
            top = matches[0]
            mem_id = top.get("id")
            old_text = top.get("memory", top.get("text", ""))
            if mem_id:
                try:
                    await delete_memory(mem_id, context.user_id)
                except Exception:
                    logger.warning("Failed to delete old memory for update: %s", mem_id)

            await add_memory(
                content=content,
                user_id=context.user_id,
                metadata={"type": "explicit", "source": "memory_update"},
            )
            return SkillResult(
                response_text=f"Updated: <b>{old_text[:80]}</b> → <b>{content[:80]}</b>"
            )

        # No match found — just save as new
        await add_memory(
            content=content,
            user_id=context.user_id,
            metadata={"type": "explicit", "source": "memory_update"},
        )
        return SkillResult(
            response_text=f"No existing fact found. Saved as new: <b>{content[:100]}</b>"
        )

    def get_system_prompt(self, context) -> str:
        return MEMORY_VAULT_SYSTEM_PROMPT


skill = MemoryVaultSkill()
