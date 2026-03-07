"""Helpers for personalization save/forget flows."""

from __future__ import annotations

import re

_FORGET_COMMAND_RE = re.compile(
    r"^\s*(?:забуд\w*|удал\w*|сотр\w*|очист\w*|forget|delete|remove|clear)\b[\s,:-]*",
    re.IGNORECASE,
)

_ALL_MARKERS = {"all", "everything", "todo", "все", "всё"}
_RULE_MARKERS = (
    "правил",
    "правило",
    "rule",
    "rules",
    "preference",
    "preferences",
    "инструкц",
    "настройк",
)
_BOT_NAME_MARKERS = (
    "как тебя зовут",
    "тебя зовут",
    "твоё имя",
    "твое имя",
    "your name",
    "bot name",
    "assistant name",
)
_USER_NAME_MARKERS = (
    "как меня зовут",
    "меня зовут",
    "моё имя",
    "мое имя",
    "my name",
    "user name",
)
_RULE_PREFIX_RE = re.compile(
    r"^\s*(?:правил[ао]?|rules?|preferences?|предпочтени[ея])\b[\s,:-]*",
    re.IGNORECASE,
)


def strip_forget_command(text: str) -> str:
    """Remove a leading forget/delete command if present."""
    stripped = text.strip()
    return _FORGET_COMMAND_RE.sub("", stripped, count=1).strip()


def has_forget_command(text: str) -> bool:
    """Return True when the text starts with a forget/delete command."""
    return strip_forget_command(text) != text.strip()


def has_all_marker(text: str) -> bool:
    """Return True when the text contains an explicit 'all/everything' marker."""
    tokens = {token.lower() for token in re.findall(r"[\wёЁ]+", text)}
    return bool(tokens & _ALL_MARKERS)


def is_clear_all_rules_request(text: str) -> bool:
    """Return True for 'forget/delete all rules' phrasing."""
    lower = text.lower()
    return has_forget_command(text) and has_all_marker(text) and any(
        marker in lower for marker in _RULE_MARKERS
    )


def is_bot_name_forget_request(text: str) -> bool:
    """Return True for 'forget your name' phrasing."""
    lower = text.lower()
    return has_forget_command(text) and any(marker in lower for marker in _BOT_NAME_MARKERS)


def is_user_name_forget_request(text: str) -> bool:
    """Return True for 'forget my name' phrasing."""
    lower = text.lower()
    return has_forget_command(text) and any(marker in lower for marker in _USER_NAME_MARKERS)


def is_personalization_forget_request(text: str) -> bool:
    """Return True for forget/delete commands aimed at memory or personalization."""
    if not has_forget_command(text):
        return False
    lower = text.lower()
    if any(marker in lower for marker in _RULE_MARKERS + _BOT_NAME_MARKERS + _USER_NAME_MARKERS):
        return True
    return bool(strip_forget_command(text))


def match_saved_rule(query: str, rules: list[str]) -> str | None:
    """Match a forget command against an existing saved rule."""
    target = strip_forget_command(query)
    if not target:
        return None
    target = _RULE_PREFIX_RE.sub("", target, count=1)
    normalized_target = _normalize_rule_text(target)
    if not normalized_target:
        return None
    for rule in rules:
        if _normalize_rule_text(rule) == normalized_target:
            return rule
    return None


def _normalize_rule_text(text: str) -> str:
    """Normalize rule text for forgiving exact-match deletion."""
    return text.strip().strip("\"'`“”‘’.,!? ").lower()
