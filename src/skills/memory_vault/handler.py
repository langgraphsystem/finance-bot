"""Memory Vault - user-controlled memory management (show / forget / save / update)."""

import logging
import re
from typing import Any

from src.core.memory.governance import explicit_memory_metadata
from src.core.observability import observe
from src.core.personalization import (
    has_all_marker,
    has_forget_command,
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

# ── Localized strings ──
_MV_STRINGS = {
    "en": {
        "identity": "Identity:",
        "your_name": "Your name: <b>{name}</b>",
        "my_name": "My name: <b>{name}</b>",
        "your_rules": "Your rules:",
        "memories_header": "Memories ({count}):",
        "memories_more": "... and {count} more.",
        "summary_prefix": "Summary: {text}",
        "no_memories": "No stored memories yet.",
        "clear_all_btn": "Clear all",
        "forget_ask": "What should I forget?",
        "rules_cleared": "All rules cleared.",
        "rules_empty": "No saved rules to clear.",
        "bot_name_forgot": "Forgot my saved name.",
        "bot_name_empty": "I don't have a saved assistant name.",
        "user_name_forgot": "Forgot your saved name.",
        "user_name_empty": "I don't have your saved name yet.",
        "rule_removed": "Removed rule: <b>{rule}</b>.",
        "rule_remove_fail": "Couldn't remove rule '{rule}'.",
        "all_cleared": "All memories cleared.",
        "no_match": "No memories found matching '{query}'.",
        "deleted": "Deleted {count} matching '{query}'.",
        "delete_fail": "Couldn't delete memories for '{query}'.",
        "calendar_delete_hint": (
            "That looks like a calendar event deletion request, not a memory delete."
        ),
        "save_ask": "What should I remember?",
        "saved": "Saved: <b>{text}</b>",
        "update_ask": "What should I update?",
        "updated": "Updated: <b>{old}</b> → <b>{new}</b>",
        "saved_new": "No existing fact found. Saved as new: <b>{text}</b>",
        "unknown": "Unknown memory action.",
    },
    "ru": {
        "identity": "Идентичность:",
        "your_name": "Твоё имя: <b>{name}</b>",
        "my_name": "Моё имя: <b>{name}</b>",
        "your_rules": "Твои правила:",
        "memories_header": "Воспоминания ({count}):",
        "memories_more": "... и ещё {count}.",
        "summary_prefix": "Сводка: {text}",
        "no_memories": "Нет сохранённых воспоминаний.",
        "clear_all_btn": "Очистить всё",
        "forget_ask": "Что забыть? Скажи, что удалить.",
        "rules_cleared": "Все правила удалены.",
        "rules_empty": "Нет сохранённых правил.",
        "bot_name_forgot": "Забыла своё имя.",
        "bot_name_empty": "У меня нет сохранённого имени.",
        "user_name_forgot": "Забыла твоё имя.",
        "user_name_empty": "У меня нет твоего сохранённого имени.",
        "rule_removed": "Удалено правило: <b>{rule}</b>.",
        "rule_remove_fail": "Не удалось удалить правило '{rule}'.",
        "all_cleared": "Все воспоминания удалены.",
        "no_match": "Не нашла воспоминаний по запросу '{query}'.",
        "deleted": "Удалено {count} по запросу '{query}'.",
        "delete_fail": "Не удалось удалить по запросу '{query}'.",
        "calendar_delete_hint": (
            "Это похоже на удаление события из календаря, а не памяти."
        ),
        "save_ask": "Что запомнить?",
        "saved": "Запомнила: <b>{text}</b>",
        "update_ask": "Что обновить?",
        "updated": "Обновлено: <b>{old}</b> → <b>{new}</b>",
        "saved_new": "Похожий факт не найден. Сохранено как новый: <b>{text}</b>",
        "unknown": "Неизвестное действие с памятью.",
    },
    "es": {
        "identity": "Identidad:",
        "your_name": "Tu nombre: <b>{name}</b>",
        "my_name": "Mi nombre: <b>{name}</b>",
        "your_rules": "Tus reglas:",
        "memories_header": "Recuerdos ({count}):",
        "memories_more": "... y {count} más.",
        "summary_prefix": "Resumen: {text}",
        "no_memories": "No hay recuerdos guardados.",
        "clear_all_btn": "Borrar todo",
        "forget_ask": "¿Qué debo olvidar?",
        "rules_cleared": "Todas las reglas eliminadas.",
        "rules_empty": "No hay reglas guardadas.",
        "bot_name_forgot": "Olvidé mi nombre.",
        "bot_name_empty": "No tengo un nombre guardado.",
        "user_name_forgot": "Olvidé tu nombre.",
        "user_name_empty": "No tengo tu nombre guardado.",
        "rule_removed": "Regla eliminada: <b>{rule}</b>.",
        "rule_remove_fail": "No pude eliminar la regla '{rule}'.",
        "all_cleared": "Todos los recuerdos eliminados.",
        "no_match": "No encontré recuerdos para '{query}'.",
        "deleted": "Eliminados {count} por '{query}'.",
        "delete_fail": "No pude eliminar por '{query}'.",
        "calendar_delete_hint": (
            "Eso parece una solicitud para eliminar un evento del calendario, no un recuerdo."
        ),
        "save_ask": "¿Qué debo recordar?",
        "saved": "Guardado: <b>{text}</b>",
        "update_ask": "¿Qué debo actualizar?",
        "updated": "Actualizado: <b>{old}</b> → <b>{new}</b>",
        "saved_new": "No hay dato similar. Guardado como nuevo: <b>{text}</b>",
        "unknown": "Acción de memoria desconocida.",
    },
}
register_strings("memory_vault", _MV_STRINGS)

_CALENDAR_DELETE_HINTS = (
    "календар",
    "событ",
    "мероприят",
    "встреч",
    "calendar",
    "event",
    "meeting",
    "appointment",
)


def _mv(key: str, lang: str, **kwargs: str) -> str:
    """Get localized memory vault string."""
    strings = _MV_STRINGS.get(lang, _MV_STRINGS.get("ru", _MV_STRINGS["en"]))
    template = strings.get(key, _MV_STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def _looks_like_calendar_delete_request(query: str) -> bool:
    """Guard against misrouting calendar deletions into memory deletion."""
    lower = query.lower().strip()
    return has_forget_command(query) and any(hint in lower for hint in _CALENDAR_DELETE_HINTS)


async def clear_all_user_memory(user_id: str) -> dict[str, int]:
    """Clear long-term user-controlled memory across vector and profile stores."""
    from src.core.memory.registry import clear_memory_registry

    cleared = await clear_memory_registry(user_id)

    return {
        "memories": cleared.get("mem0", 0),
        "rules": cleared.get("rule", 0),
        "identity_fields": cleared.get("identity", 0),
        "summaries": cleared.get("summary", 0),
    }


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
            delete_memory,
            get_all_memories,
            search_memories_all_namespaces,
        )
        from src.core.memory.registry import (
            delete_registry_entry,
            list_memory_registry,
            search_memory_registry,
        )

        lang = getattr(context, "language", None) or "ru"
        intent = intent_data.get("_intent") or "memory_show"

        if intent == "memory_show":
            return await self._handle_show(context, list_memory_registry, lang)

        if intent == "memory_forget":
            query = intent_data.get("memory_query") or message.text or ""
            return await self._handle_forget(
                context,
                query,
                search_memory_registry,
                delete_registry_entry,
                get_all_memories,
                delete_memory,
                lang,
            )

        if intent == "memory_save":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_save(context, content, add_memory, lang)

        if intent == "memory_update":
            content = intent_data.get("memory_query") or message.text or ""
            return await self._handle_update(
                context,
                content,
                search_memories_all_namespaces,
                delete_memory,
                add_memory,
                lang,
            )

        return SkillResult(response_text=_mv("unknown", lang))

    async def _handle_show(self, context, list_memory_registry, lang: str) -> SkillResult:
        entries = await list_memory_registry(context.user_id)

        sections: list[str] = []
        identity_entries = [entry for entry in entries if entry.get("store") == "identity"]
        if identity_entries:
            id_lines: list[str] = []
            for entry in identity_entries:
                field = str(entry.get("field") or entry.get("source_id") or "")
                text = str(entry.get("text") or "").strip()
                if not text:
                    continue
                if field == "name":
                    id_lines.append("• " + _mv("your_name", lang, name=text))
                elif field == "bot_name":
                    id_lines.append("• " + _mv("my_name", lang, name=text))
                else:
                    label = field.replace("_", " ").capitalize()
                    id_lines.append(f"• {label}: <b>{text}</b>")
            if id_lines:
                sections.append(
                    f"<b>{_mv('identity', lang)}</b>\n" + "\n".join(id_lines)
                )

        rule_entries = [entry for entry in entries if entry.get("store") == "rule"]
        if rule_entries:
            rule_lines = "\n".join(
                f"• {entry['text']}" for entry in rule_entries if entry.get("text")
            )
            if rule_lines:
                sections.append(f"<b>{_mv('your_rules', lang)}</b>\n{rule_lines}")

        mem_lines = []
        memory_entries = [
            entry for entry in entries
            if entry.get("store") in {"mem0", "summary"}
        ]
        for index, entry in enumerate(memory_entries[:MAX_DISPLAY_MEMORIES], 1):
            text = str(entry.get("display_text") or entry.get("text") or "").strip()
            if text:
                if entry.get("store") == "summary":
                    text = _mv("summary_prefix", lang, text=text)
                mem_lines.append(f"{index}. {text}")

        if mem_lines:
            extra = ""
            if len(memory_entries) > MAX_DISPLAY_MEMORIES:
                remaining = len(memory_entries) - MAX_DISPLAY_MEMORIES
                extra = "\n" + _mv("memories_more", lang, count=str(remaining))
            header = _mv("memories_header", lang, count=str(len(memory_entries)))
            sections.append(f"<b>{header}</b>\n" + "\n".join(mem_lines) + extra)

        if not sections:
            return SkillResult(response_text=_mv("no_memories", lang))

        return SkillResult(
            response_text="\n\n".join(sections),
            buttons=[
                {"text": _mv("clear_all_btn", lang), "callback": "memory:clear_all"},
            ],
        )

    async def _handle_forget(
        self,
        context,
        query,
        search_memory_registry,
        delete_registry_entry,
        get_all_memories,
        delete_memory,
        lang: str,
    ) -> SkillResult:
        from src.core.identity import (
            clear_identity_fields,
            clear_user_rules,
            get_user_rules,
            remove_user_rule,
        )

        query = query.strip()
        if not query:
            return SkillResult(response_text=_mv("forget_ask", lang))
        if _looks_like_calendar_delete_request(query):
            return SkillResult(response_text=_mv("calendar_delete_hint", lang))

        if is_clear_all_rules_request(query):
            deleted_rules = await clear_user_rules(context.user_id)
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"user_rule"},
            )
            if deleted_rules:
                return SkillResult(response_text=_mv("rules_cleared", lang))
            return SkillResult(response_text=_mv("rules_empty", lang))

        if is_bot_name_forget_request(query):
            deleted_fields = await clear_identity_fields(context.user_id, ["bot_name"])
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"bot_identity"},
            )
            if deleted_fields:
                return SkillResult(response_text=_mv("bot_name_forgot", lang))
            return SkillResult(response_text=_mv("bot_name_empty", lang))

        if is_user_name_forget_request(query):
            deleted_fields = await clear_identity_fields(context.user_id, ["name"])
            await self._delete_personalization_memories(
                context.user_id,
                get_all_memories,
                delete_memory,
                categories={"user_identity"},
            )
            if deleted_fields:
                return SkillResult(response_text=_mv("user_name_forgot", lang))
            return SkillResult(response_text=_mv("user_name_empty", lang))

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
                return SkillResult(response_text=_mv("rule_removed", lang, rule=matched_rule))
            return SkillResult(response_text=_mv("rule_remove_fail", lang, rule=matched_rule))

        if _is_clear_all_memory_request(query):
            await clear_all_user_memory(context.user_id)
            return SkillResult(response_text=_mv("all_cleared", lang))

        matches = await search_memory_registry(context.user_id, query, limit=3)
        if not matches:
            return SkillResult(response_text=_mv("no_match", lang, query=query))

        deleted = 0
        for entry in matches:
            try:
                deleted += int(await delete_registry_entry(context.user_id, entry))
            except Exception:
                logger.warning(
                    "Failed to delete memory registry entry %s",
                    entry.get("id"),
                    exc_info=True,
                )

        if deleted:
            return SkillResult(
                response_text=_mv("deleted", lang, count=str(deleted), query=query)
            )
        return SkillResult(response_text=_mv("delete_fail", lang, query=query))

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

    async def _handle_save(self, context, content, add_memory, lang: str) -> SkillResult:
        content = content.strip()
        if not content:
            return SkillResult(response_text=_mv("save_ask", lang))

        category = _infer_explicit_memory_category(content)
        await add_memory(
            content=content,
            user_id=context.user_id,
            metadata=explicit_memory_metadata(
                source="memory_vault",
                category=category,
            ),
        )
        return SkillResult(response_text=_mv("saved", lang, text=content[:100]))

    async def _handle_update(
        self,
        context,
        content,
        search_memories,
        delete_memory,
        add_memory,
        lang: str,
    ) -> SkillResult:
        """Update an existing memory fact."""
        content = content.strip()
        if not content:
            return SkillResult(response_text=_mv("update_ask", lang))

        matches = await search_memories(content, context.user_id, limit=3)
        if matches:
            top = matches[0]
            mem_id = top.get("id")
            old_text = top.get("memory", top.get("text", ""))
            category = _infer_explicit_memory_category(content, top)
            if mem_id:
                try:
                    await delete_memory(mem_id, context.user_id)
                except Exception:
                    logger.warning("Failed to delete old memory for update: %s", mem_id)

            await add_memory(
                content=content,
                user_id=context.user_id,
                metadata=explicit_memory_metadata(
                    source="memory_update",
                    category=category,
                    existing_memory=top,
                ),
            )
            return SkillResult(
                response_text=_mv("updated", lang, old=old_text[:80], new=content[:80])
            )

        category = _infer_explicit_memory_category(content)
        await add_memory(
            content=content,
            user_id=context.user_id,
            metadata=explicit_memory_metadata(
                source="memory_update",
                category=category,
            ),
        )
        return SkillResult(response_text=_mv("saved_new", lang, text=content[:100]))

    def get_system_prompt(self, context) -> str:
        return MEMORY_VAULT_SYSTEM_PROMPT


skill = MemoryVaultSkill()



def _normalize_memory_text(text: str) -> str:
    return text.strip().strip("\"'`“”‘’.,!? ").lower()



def _infer_explicit_memory_category(
    text: str,
    existing_memory: dict[str, Any] | None = None,
) -> str:
    if existing_memory:
        metadata = existing_memory.get("metadata") or {}
        existing_category = metadata.get("category") or existing_memory.get("category")
        if isinstance(existing_category, str) and existing_category.strip():
            return existing_category.strip()

    lower = text.lower()
    if any(marker in lower for marker in ("меня зовут", "my name is", "моё имя", "мое имя")):
        return "user_identity"
    if any(marker in lower for marker in ("зови себя", "your name is", "тебя зовут")):
        return "bot_identity"
    if any(marker in lower for marker in ("без эмодзи", "отвечай", "reply in", "always respond")):
        return "user_rule"
    if any(
        marker in lower for marker in ("предпочитаю", "i prefer", "люблю", "i like", "нравится")
    ):
        return "user_preference"
    return "life_note"


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
