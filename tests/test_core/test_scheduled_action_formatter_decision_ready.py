"""Tests for decision-ready structure enforcement in SIA formatter."""

from src.core.scheduled_actions.formatter import (
    _decision_ready_system,
    _ensure_decision_ready_structure,
)


def test_decision_ready_system_requires_ranked_priorities_and_recommended_action():
    system_prompt = _decision_ready_system("en")

    assert "MUST be top priorities" in system_prompt
    assert "deadlines, money impact, and risk signals" in system_prompt
    assert "exactly one recommended next action" in system_prompt


def test_ensure_decision_ready_structure_adds_required_sections():
    raw = "<b>Good morning</b>\n• Task A\n• Task B"

    normalized = _ensure_decision_ready_structure(raw, "en")

    assert "🎯 <b>Top priorities</b>" in normalized
    assert "➡️ <b>Recommended next action</b>" in normalized
    assert "Start with the highest-urgency item now" in normalized


def test_ensure_decision_ready_structure_preserves_existing_headers():
    raw = (
        "🎯 <b>Top priorities</b>\n"
        "• Pay invoice today\n\n"
        "➡️ <b>Recommended next action</b>\n"
        "• Call the vendor now."
    )

    normalized = _ensure_decision_ready_structure(raw, "en")

    assert normalized.count("Top priorities") == 1
    assert normalized.count("Recommended next action") == 1
