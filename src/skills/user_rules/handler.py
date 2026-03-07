"""Skill: set_user_rule — personalization and user rules management.

Handles: "отвечай коротко", "зови себя X", "без эмодзи", "пиши на русском",
"your name is X", "no emoji", "always respond in English".
"""

import logging

from src.core.personalization import is_personalization_forget_request
from src.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class UserRuleSkill(BaseSkill):
    name = "user_rules"
    intents = ["set_user_rule"]
    model = "gemini-3.1-flash-lite-preview"

    def get_system_prompt(self, context) -> str:  # noqa: ANN001, ARG002
        return ""

    async def execute(self, message, context, intent_data=None) -> SkillResult:  # noqa: ANN001
        from src.core.identity import (
            get_user_rules,
            immediate_identity_update,
            is_valid_user_rule,
        )
        from src.core.memory.mem0_client import add_memory
        from src.skills.memory_vault.handler import skill as memory_vault_skill

        text = (intent_data or {}).get("rule_text") or message.text or ""
        if not text or not text.strip():
            return SkillResult(response_text=_msg("empty", context.language))

        rule_text = text.strip()
        if is_personalization_forget_request(rule_text):
            return await memory_vault_skill.execute(
                message,
                context,
                {"_intent": "memory_forget", "memory_query": rule_text},
            )

        if not is_valid_user_rule(rule_text):
            logger.info("Rejected invalid user rule text: %s", rule_text[:80])
            return SkillResult(response_text=_msg("invalid_rule", context.language or "en"))

        user_id = str(context.user_id)
        language = context.language or "en"

        # Detect rule type and apply
        rule_type = _classify_rule(rule_text)

        if rule_type == "bot_name":
            await immediate_identity_update(user_id, "bot_identity", rule_text)
            # Also save to Mem0 for long-term
            await add_memory(
                rule_text, user_id=user_id,
                metadata={"category": "bot_identity"},
            )
            bot_name = _extract_name(rule_text)
            return SkillResult(
                response_text=_msg("bot_name", language, name=bot_name),
            )

        if rule_type == "user_name":
            await immediate_identity_update(user_id, "user_identity", rule_text)
            await add_memory(
                rule_text, user_id=user_id,
                metadata={"category": "user_identity"},
            )
            user_name = _extract_name(rule_text)
            return SkillResult(
                response_text=_msg("user_name", language, name=user_name),
            )

        # General rule (style, language, emoji, etc.)
        await immediate_identity_update(user_id, "user_rule", rule_text)
        await add_memory(
            rule_text, user_id=user_id,
            metadata={"category": "user_rule"},
        )

        current_rules = await get_user_rules(user_id)
        rules_display = "\n".join(f"• {r}" for r in current_rules) if current_rules else ""

        return SkillResult(
            response_text=_msg("rule_saved", language, rule=rule_text, rules=rules_display),
        )


def _classify_rule(text: str) -> str:
    """Classify rule type based on keywords."""
    lower = text.lower()

    bot_name_markers = [
        "зови себя", "тебя зовут", "твоё имя", "твое имя",
        "call yourself", "your name is", "ты —", "ты -",
        "имя бота", "назовись",
    ]
    if any(m in lower for m in bot_name_markers):
        return "bot_name"

    user_name_markers = [
        "меня зовут", "моё имя", "мое имя", "my name is",
        "i am ", "я —", "я -",
    ]
    if any(m in lower for m in user_name_markers):
        return "user_name"

    return "general_rule"


def _extract_name(text: str) -> str:
    """Extract a name from rule text."""
    lower = text.lower()
    patterns = [
        "зови себя ", "тебя зовут ", "твоё имя ", "твое имя ",
        "call yourself ", "your name is ", "имя бота: ", "имя бота ",
        "меня зовут ", "моё имя ", "мое имя ", "my name is ",
        "назовись ",
    ]
    for p in patterns:
        if p in lower:
            idx = lower.index(p) + len(p)
            return text[idx:].strip().strip(".,!\"'")

    return text.strip()


def _msg(key: str, language: str, **kwargs: str) -> str:
    """Get a localized response message."""
    is_ru = language and language.startswith("ru")

    messages = {
        "empty": {
            "ru": "Пожалуйста, укажите правило или предпочтение.",
            "en": "Please specify a rule or preference.",
        },
        "bot_name": {
            "ru": "Запомнила! Теперь моё имя — <b>{name}</b>.",
            "en": "Got it! My name is now <b>{name}</b>.",
        },
        "user_name": {
            "ru": "Приятно познакомиться, <b>{name}</b>! Запомнила.",
            "en": "Nice to meet you, <b>{name}</b>! Saved.",
        },
        "rule_saved": {
            "ru": "Запомнила правило: <b>{rule}</b>\n\nТекущие правила:\n{rules}",
            "en": "Rule saved: <b>{rule}</b>\n\nCurrent rules:\n{rules}",
        },
        "invalid_rule": {
            "ru": "Это похоже на обычный запрос, а не на постоянное правило для бота.",
            "en": "That looks like a normal request, not a persistent bot rule.",
        },
    }

    lang_key = "ru" if is_ru else "en"
    template = messages.get(key, {}).get(lang_key, messages.get(key, {}).get("en", "OK"))
    return template.format(**kwargs)


skill = UserRuleSkill()
