"""Tests for scoped intent detection (supervisor-backed two-stage pipeline)."""

import pytest

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


# ---------------------------------------------------------------------------
# B1: SIA intent support — acceptance tests
# ---------------------------------------------------------------------------


def test_scoped_intent_defs_include_sia_intents():
    """All 3 SIA intents must be in the tasks domain scoped intent defs."""
    tasks_defs = SCOPED_INTENT_DEFS.get("tasks", {})
    for intent in ("schedule_action", "list_scheduled_actions", "manage_scheduled_action"):
        assert intent in tasks_defs, f"SIA intent '{intent}' missing from tasks SCOPED_INTENT_DEFS"


def test_scoped_prompt_tasks_includes_sia_intents():
    """Tasks scoped prompt should contain SIA intent names."""
    sia_skills = [
        "create_task", "list_tasks", "set_reminder", "complete_task",
        "schedule_action", "list_scheduled_actions", "manage_scheduled_action",
    ]
    prompt = _build_scoped_prompt("tasks", sia_skills)
    assert "schedule_action" in prompt
    assert "list_scheduled_actions" in prompt
    assert "manage_scheduled_action" in prompt


def test_full_intent_prompt_includes_sia_examples():
    """Full INTENT_DETECTION_PROMPT must have SIA intent definitions + examples."""
    from src.core.intent import INTENT_DETECTION_PROMPT

    prompt = INTENT_DETECTION_PROMPT
    assert "schedule_action" in prompt
    assert "list_scheduled_actions" in prompt
    assert "manage_scheduled_action" in prompt


def test_intent_data_has_schedule_fields():
    """IntentData must include all SIA-specific fields."""
    from src.core.schemas.intent import IntentData

    sia_fields = [
        "schedule_frequency",
        "schedule_time",
        "schedule_day_of_week",
        "schedule_day_of_month",
        "schedule_sources",
        "schedule_instruction",
        "schedule_output_mode",
        "schedule_action_kind",
        "schedule_completion_condition",
        "schedule_end_date",
        "schedule_max_runs",
        "managed_action_title",
        "manage_operation",
    ]
    model_fields = set(IntentData.model_fields.keys())
    for field in sia_fields:
        assert field in model_fields, f"IntentData missing SIA field '{field}'"


def test_intent_data_schedule_fields_parse_correctly():
    """IntentData should correctly parse schedule-related fields."""
    from src.core.schemas.intent import IntentData

    data = IntentData(
        schedule_frequency="daily",
        schedule_time="08:00",
        schedule_sources=["calendar", "tasks", "money_summary"],
        schedule_instruction="Send me a morning brief",
        schedule_output_mode="compact",
        schedule_max_runs=30,
    )
    assert data.schedule_frequency == "daily"
    assert data.schedule_time == "08:00"
    assert data.schedule_sources == ["calendar", "tasks", "money_summary"]
    assert data.schedule_max_runs == 30


@pytest.mark.parametrize("phrase,expected_intent", [
    ("schedule_action", "schedule_action"),
    ("list_scheduled_actions", "list_scheduled_actions"),
    ("manage_scheduled_action", "manage_scheduled_action"),
])
def test_sia_intents_in_domain_mapping(phrase, expected_intent):
    """SIA intents must be mapped to tasks domain."""
    from src.core.domains import INTENT_DOMAIN_MAP, Domain

    assert expected_intent in INTENT_DOMAIN_MAP
    assert INTENT_DOMAIN_MAP[expected_intent] == Domain.tasks


def test_sia_intents_in_skill_catalog():
    """SIA skills must be listed in the tasks domain of skill_catalog.yaml."""
    from src.core.skill_catalog import load_catalog

    catalog = load_catalog.__wrapped__()
    tasks_domain = catalog.domains.get("tasks")
    assert tasks_domain is not None
    for skill in ("schedule_action", "list_scheduled_actions", "manage_scheduled_action"):
        assert skill in tasks_domain.skills, f"SIA skill '{skill}' missing from tasks catalog"
