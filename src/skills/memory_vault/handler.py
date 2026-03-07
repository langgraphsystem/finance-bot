"""Memory Vault - user-controlled memory management (show / forget / save / update)."""

import logging
import re
from typing import Any

from src.core.observability import observe
from src.core.personalization import (
    has_all_marker,
    is_bot_name_forget_request,
    is_clear_all_rules_request,
    is_user_name_forget_request,
    match_saved_rule,
    strip_forget_command,
)
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
    model = "gpt-5.2"

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
            search_memories_all_namespaces,
        )

        intent = intent_data.get("_intent") or "memory_show"

        if intent == "memory_show":
            return await self._handle_show(context, get_all_memories)

        if intent == "memory_forget":
            query = intent_data.get("memory_query") or message.text or ""
            return await self._handle_forget(
                context,
                query,
                search_memories_all_namespaces,
                delete_memory,
                delete_all_memories,
                get_all_memories,
            )

        if intent == "memory_save":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_save(context, content, add_memory)

        if intent == "memory_update":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_update(
                context,
                content,
                search_memories_all_namespaces,
                delete_memory,
                add_memory,
            )

        return SkillResult(response_text="Unknown memory action.")

    async def _handle_show(self, context, get_all_memories) -> SkillResult:
        from src.core.identity import get_core_identity, get_user_rules

        memories = await get_all_memories(context.user_id)

        sections: list[str] = []
        try:
            identity = await get_core_identity(context.user_id)
            if identity:
                id_lines: list[str] = []
                if identity.get("name"):
                    id_lines.append(f"• Your name: <b>{identity['name']}</b>")
                if identity.get("bot_name"):
                    id_lines.append(f"• My name: <b>{identity['bot_name']}</b>")
                if id_lines:
                    sections.append("<b>Identity:</b>\n" + "\n".join(id_lines))

            rules = await get_user_rules(context.user_id)
            if rules:
                rule_lines = "\n".join(f"• {rule}" for rule in rules)
                sections.append(f"<b>Your rules:</b>\n{rule_lines}")
        except Exception:
            logger.warning("Failed to load core identity for memory_show", exc_info=True)

        mem_lines = []
        for index, mem in enumerate(memories[:MAX_DISPLAY_MEMORIES], 1):
            text = mem.get("memory", mem.get("text", ""))
            if text:
                mem_lines.append(f"{index}. {text}")

        if mem_lines:
            extra = ""
            if len(memories) > MAX_DISPLAY_MEMORIES:
                extra = f"\n... and {len(memories) - MAX_DISPLAY_MEMORIES} more."
            sections.append(f"<b>Memories ({len(memories)}):</b>\n" + "\n".join(mem_lines) + extra)

        if not sections:
            return SkillResult(response_text="No stored memories yet.")

        return SkillResult(
            response_text="\n\n".join(sections),
            buttons=[
                {"text": "Clear all", "callback": "memory:clear_all"},
            ],
        )

    async def _handle_forget(
        self,
        context,
        query,
        search_memories,
        delete_memory,
        delete_all_memories,
        get_all_memories,
    ) -> SkillResult:
        from src.core.identity import (
            clear_identity_fields,
            clear_user_rules,
            get_user_rules,
            remove_user_rule,
        )

        query = query.strip()
        if not query:
            return SkillResult(response_text="What should I forget? Tell me what to remove.")

        if is_clear_all_rules_request(query):
            deleted_rules = await clear_user_rules(context.user_id)
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"user_rule"},
            )
            if deleted_rules:
                return SkillResult(response_text="Cleared all saved rules.")
            return SkillResult(response_text="I couldn't find any saved rules to clear.")

        if is_bot_name_forget_request(query):
            deleted_fields = await clear_identity_fields(context.user_id, ["bot_name"])
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"bot_identity"},
            )
            if deleted_fields:
                return SkillResult(response_text="Forgot my saved name.")
            return SkillResult(response_text="I don't have a saved assistant name.")

        if is_user_name_forget_request(query):
            deleted_fields = await clear_identity_fields(context.user_id, ["name"])
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"user_identity"},
            )
            if deleted_fields:
                return SkillResult(response_text="Forgot your saved name.")
            return SkillResult(response_text="I don't have your saved name yet.")

        saved_rules = await get_user_rules(context.user_id)
        matched_rule = match_saved_rule(query, saved_rules)
        if matched_rule:
            removed = await remove_user_rule(context.user_id, matched_rule)
            if removed:
                await self._delete_personalization_memories(
                    context.user_id,
                    get_all_memories,
                    delete_memory,
                    categories={"user_rule"},
                    exact_texts={matched_rule},
                )
                return SkillResult(response_text=f"Removed saved rule: <b>{matched_rule}</b>.")
            return SkillResult(response_text=f"I couldn't remove the saved rule '{matched_rule}'.")

        if _is_clear_all_memory_request(query):
            await delete_all_memories(context.user_id)
            return SkillResult(response_text="All memories cleared.")

        matches = await search_memories(query, context.user_id, limit=5)
        if not matches:
            return SkillResult(response_text=f"No memories found matching '{query}'.")

        deleted = 0
        for mem in matches:
            mem_id = mem.get("id")
            if not mem_id:
                continue
            try:
                await delete_memory(mem_id, context.user_id)
                deleted += 1
            except Exception:
                logger.warning("Failed to delete memory %s", mem_id, exc_info=True)

        if deleted:
            suffix = "s" if deleted > 1 else ""
            return SkillResult(
                response_text=f"Deleted {deleted} memory{suffix} matching '{query}'."
            )
        return SkillResult(response_text=f"Could not delete memories for '{query}'.")

    async def _delete_personalization_memories(
        self,
        user_id,
        get_all_memories,
        delete_memory,
        categories: set[str],
        exact_texts: set[str] | None = None,
    ) -> int:
        memories = await get_all_memories(user_id)
        if not memories:
            return 0

        normalized_texts = {_normalize_memory_text(text) for text in exact_texts or set()}
        deleted = 0
        for mem in memories:
            mem_id = mem.get("id")
            if not mem_id:
                continue

            text = mem.get("memory") or mem.get("text") or ""
            metadata = mem.get("metadata") or {}
            category = metadata.get("category") or mem.get("category")
            matches_category = category in categories
            matches_text = (
                _normalize_memory_text(text) in normalized_texts if normalized_texts else False
            )
            if not matches_category and not matches_text:
                continue

            try:
                await delete_memory(mem_id, user_id)
                deleted += 1
            except Exception:
                logger.warning("Failed to delete personalization memory %s", mem_id, exc_info=True)

        return deleted

    async def _handle_save(self, context, content, add_memory) -> SkillResult:
        content = content.strip()
        if not content:
            return SkillResult(response_text="What should I remember?")

        await add_memory(
            content=content,
            user_id=context.user_id,
            metadata={"type": "explicit", "source": "memory_vault"},
        )
        return SkillResult(response_text=f"Saved: <b>{content[:100]}</b>")

    async def _handle_update(
        self,
        context,
        content,
        search_memories,
        delete_memory,
        add_memory,
    ) -> SkillResult:
        """Update an existing memory fact."""
        content = content.strip()
        if not content:
            return SkillResult(response_text="What should I update?")

        matches = await search_memories(content, context.user_id, limit=3)
        if matches:
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



def _normalize_memory_text(text: str) -> str:
    return text.strip().strip("\"'`“”‘’.,!? ").lower()



def _is_clear_all_memory_request(query: str) -> bool:
    remainder = strip_forget_command(query)
    if not remainder or not has_all_marker(remainder):
        return False
    tokens = {token.lower() for token in re.findall(r"[\wёЁ]+", remainder)}
    allowed = {
        "all",
        "everything",
        "todo",
        "все",
        "всё",
        "memory",
        "memories",
        "память",
        "памяти",
        "воспоминание",
        "воспоминания",
    }
    return tokens <= allowed
