"""Tests for AddExpenseSkill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.skills.add_expense.handler import skill


def test_skill_uses_allowed_model():
    assert skill.model == "gpt-5.2"


# ---------------------------------------------------------------------------
# 1. No amount → error message
# ---------------------------------------------------------------------------
async def test_no_amount_returns_error(sample_context, text_message):
    intent_data = {"merchant": "Shell", "category": "Дизель", "confidence": 0.9}

    result = await skill.execute(text_message, sample_context, intent_data)

    assert "Не удалось определить сумму" in result.response_text


# ---------------------------------------------------------------------------
# 2. Unknown category → buttons for category selection
# ---------------------------------------------------------------------------
async def test_unknown_category_shows_buttons(sample_context, text_message):
    intent_data = {
        "amount": 50.0,
        "merchant": "Random Store",
        "category": "НесуществующаяКатегория",
        "confidence": 0.9,
    }

    with patch("src.skills.add_expense.handler.log_action", new_callable=AsyncMock):
        result = await skill.execute(text_message, sample_context, intent_data)

    assert result.buttons is not None
    assert len(result.buttons) > 0


# ---------------------------------------------------------------------------
# 3. High confidence → saves transaction, returns confirm/correct/cancel buttons
# ---------------------------------------------------------------------------
async def test_high_confidence_saves_transaction(sample_context, text_message):
    cat = sample_context.categories[0]  # dict: {"id": ..., "name": "Дизель", ...}
    intent_data = {
        "amount": 120.50,
        "merchant": "Pilot Flying J",
        "category": cat["name"],
        "confidence": 0.95,
        "scope": "personal",
        "date": None,
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    with (
        patch(
            "src.skills.add_expense.handler.get_session",
            return_value=mock_session,
        ),
        patch("src.skills.add_expense.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(text_message, sample_context, intent_data)

    assert mock_session.add.called
    assert mock_session.commit.called
    assert "120" in result.response_text
    assert result.buttons is not None


# ---------------------------------------------------------------------------
# 4. Low confidence → asks confirmation, no DB call
# ---------------------------------------------------------------------------
async def test_low_confidence_asks_confirmation(sample_context, text_message):
    cat = sample_context.categories[0]
    intent_data = {
        "amount": 45.0,
        "merchant": "Unknown Gas",
        "category": cat["name"],
        "confidence": 0.7,
        "scope": "personal",
        "date": None,
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "src.skills.add_expense.handler.get_session",
            return_value=mock_session,
        ),
        patch("src.skills.add_expense.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(text_message, sample_context, intent_data)

    assert not mock_session.commit.called
    assert result.buttons is not None


# ---------------------------------------------------------------------------
# 5. _resolve_category is case-insensitive
# ---------------------------------------------------------------------------
async def test_resolve_category_case_insensitive(sample_context):
    cat = sample_context.categories[0]  # dict
    upper_name = cat["name"].upper()
    lower_name = cat["name"].lower()

    resolved_upper = skill._resolve_category(upper_name, sample_context)
    resolved_lower = skill._resolve_category(lower_name, sample_context)

    assert resolved_upper is not None
    assert resolved_lower is not None
    assert resolved_upper == cat["id"]
    assert resolved_lower == cat["id"]


def test_system_prompt_forbids_category_hallucination(sample_context):
    prompt = skill.get_system_prompt(sample_context)
    assert "ТОЛЬКО из списка" in prompt
    assert "Не придумывай новые категории" in prompt
