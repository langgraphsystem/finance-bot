"""Tests for SkillRegistry."""


def test_registry_has_all_skills(skill_registry):
    skills = skill_registry.all_skills()
    assert len(skills) == 32


def test_registry_routes_intents(skill_registry):
    intents = [
        "add_expense",
        "add_income",
        "onboarding",
        "scan_receipt",
        "query_stats",
        "general_chat",
        "correct_category",
        "undo_last",
        "query_report",
        "set_budget",
        "mark_paid",
        "add_recurring",
        "complex_query",
        "quick_capture",
        "track_food",
        "track_drink",
        "mood_checkin",
        "day_plan",
        "day_reflection",
        "life_search",
        "set_comm_mode",
        "create_task",
        "list_tasks",
        "set_reminder",
        "complete_task",
        "quick_answer",
        "web_search",
        "compare_options",
        "draft_message",
        "translate_text",
        "write_post",
        "proofread",
    ]
    for intent in intents:
        skill = skill_registry.get(intent)
        assert skill is not None, f"No skill for intent: {intent}"


def test_registry_returns_none_for_unknown(skill_registry):
    assert skill_registry.get("unknown_intent") is None


def test_each_skill_has_required_attributes(skill_registry):
    for s in skill_registry.all_skills():
        assert hasattr(s, "name")
        assert hasattr(s, "intents")
        assert hasattr(s, "model")
        assert hasattr(s, "execute")
        assert hasattr(s, "get_system_prompt")
