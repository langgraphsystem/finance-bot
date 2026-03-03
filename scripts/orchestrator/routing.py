"""Task routing logic — decides which agent handles a task."""

from __future__ import annotations

ROUTING_RULES: dict[str, dict] = {
    # Codex — well-defined, pattern-based, tedious tasks
    "write_tests": {
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "reason": "pattern-based test generation",
    },
    "bulk_refactor": {
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "reason": "large-scope mechanical changes",
    },
    "code_review": {
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "reason": "catches edge-cases",
    },
    "fix_bug": {
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "reason": "clear repro, scoped fix",
    },
    "migrate_api": {
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "reason": "version migration is methodical",
    },
    # Gemini — fast prototyping, large context, text generation
    "ui_prototype": {"agent": "gemini", "reason": "fast UI generation"},
    "research_codebase": {"agent": "gemini", "reason": "1M context for codebase analysis"},
    "generate_docs": {"agent": "gemini", "reason": "strong at text and spec generation"},
    "analyze_code": {"agent": "gemini", "reason": "large context window for analysis"},
    # Both — critical code, want best result
    "critical_code": {"agent": "both", "reason": "parallel execution, pick best"},
}

# Keywords in prompt → task type (for auto-routing when --task not specified)
KEYWORD_HINTS: list[tuple[list[str], str]] = [
    (["test", "тест", "cover"], "write_tests"),
    (["refactor", "рефактор", "rename", "replace all", "замени"], "bulk_refactor"),
    (["review", "ревью", "check my", "проверь"], "code_review"),
    (["fix", "bug", "баг", "фикс", "broken", "сломан"], "fix_bug"),
    (["migrate", "миграц", "upgrade", "обнови версию"], "migrate_api"),
    (["ui", "html", "css", "frontend", "фронтенд", "страниц"], "ui_prototype"),
    (["research", "find all", "найди все", "analyze", "анализ"], "research_codebase"),
    (["doc", "readme", "документ", "spec", "спек"], "generate_docs"),
]


def route_task(task_type: str | None, prompt: str, explicit_agent: str | None = None) -> dict:
    """Determine which agent should handle this task.

    Priority:
    1. Explicit agent override (user said @codex / @gemini)
    2. Explicit task_type from --task flag
    3. Auto-detect from prompt keywords
    4. Fallback to codex (most versatile for code tasks)
    """
    # 1. User explicitly chose an agent
    if explicit_agent:
        if explicit_agent == "both":
            return {"agent": "both", "reason": "user requested parallel execution"}
        return {"agent": explicit_agent, "reason": "user explicitly chose agent"}

    # 2. Explicit task type
    if task_type and task_type in ROUTING_RULES:
        return ROUTING_RULES[task_type]

    # 3. Auto-detect from prompt
    if prompt:
        prompt_lower = prompt.lower()
        for keywords, detected_task in KEYWORD_HINTS:
            if any(kw in prompt_lower for kw in keywords):
                rule = ROUTING_RULES.get(detected_task, {})
                return {
                    "agent": rule.get("agent", "codex"),
                    "model": rule.get("model"),
                    "reason": f"auto-detected '{detected_task}' from prompt keywords",
                    "detected_task": detected_task,
                }

    # 4. Fallback
    return {"agent": "codex", "reason": "fallback — codex is most versatile for code tasks"}
