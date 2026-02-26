"""Tests for scoped intent detection (supervisor-backed two-stage pipeline)."""

from src.core.intent import (
    SCOPED_INTENT_DEFS,
    _build_scoped_prompt,
)


def test_scoped_intent_defs_cover_all_domains():
    """All catalog domains should have scoped intent definitions."""
    from src.core.skill_catalog import load_catalog

    catalog = load_catalog.__wrapped__()
    for domain_name in catalog.domains:
        assert domain_name in SCOPED_INTENT_DEFS, (
            f"Domain '{domain_name}' missing from SCOPED_INTENT_DEFS"
        )


def test_scoped_intent_defs_match_catalog_skills():
    """Scoped intent defs should cover all skills in each catalog domain."""
    from src.core.skill_catalog import load_catalog

    catalog = load_catalog.__wrapped__()
    for domain_name, group in catalog.domains.items():
        defs = SCOPED_INTENT_DEFS.get(domain_name, {})
        for skill in group.skills:
            assert skill in defs, (
                f"Skill '{skill}' in domain '{domain_name}' "
                f"missing from SCOPED_INTENT_DEFS"
            )


def test_build_scoped_prompt_finance():
    """Scoped prompt for finance domain should be compact."""
    prompt = _build_scoped_prompt("finance", [
        "add_expense", "add_income", "set_budget", "general_chat",
    ])
    assert "add_expense" in prompt
    assert "add_income" in prompt
    assert "set_budget" in prompt
    assert "general_chat" in prompt
    assert "Домен: finance" in prompt
    # Should be compact — well under 3K chars
    assert len(prompt) < 3000


def test_build_scoped_prompt_tasks():
    """Scoped prompt for tasks domain should list task intents."""
    prompt = _build_scoped_prompt("tasks", [
        "create_task", "list_tasks", "set_reminder", "complete_task",
    ])
    assert "create_task" in prompt
    assert "set_reminder" in prompt
    assert "Домен: tasks" in prompt


def test_build_scoped_prompt_includes_data_rules():
    """Scoped prompt should include data extraction rules."""
    prompt = _build_scoped_prompt("email", ["read_inbox", "send_email"])
    assert "Извлеки данные" in prompt
    assert "amount" in prompt
    assert "date" in prompt


def test_build_scoped_prompt_much_smaller_than_full():
    """Scoped prompt should be significantly smaller than full prompt."""
    from src.core.intent import INTENT_DETECTION_PROMPT

    full_len = len(INTENT_DETECTION_PROMPT)
    scoped = _build_scoped_prompt("email", [
        "read_inbox", "send_email", "draft_reply",
        "follow_up_email", "summarize_thread",
    ])
    scoped_len = len(scoped)

    # Scoped should be at least 3x smaller than full
    assert scoped_len < full_len / 3, (
        f"Scoped prompt ({scoped_len}) should be <{full_len // 3} (1/3 of full)"
    )


def test_all_domains_have_general_chat_in_prompt():
    """Every scoped prompt should include general_chat as fallback."""
    from src.core.skill_catalog import load_catalog

    catalog = load_catalog.__wrapped__()
    for domain_name, group in catalog.domains.items():
        prompt = _build_scoped_prompt(domain_name, list(group.skills))
        assert "general_chat" in prompt, (
            f"Scoped prompt for '{domain_name}' should include general_chat"
        )
