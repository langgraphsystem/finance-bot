"""Tests for AddIncomeSkill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.skills.add_income.handler import skill


def test_skill_uses_allowed_model():
    assert skill.model == "gpt-5.2"


# ---------------------------------------------------------------------------
# 1. No amount → error message
# ---------------------------------------------------------------------------
async def test_no_amount_returns_error(sample_context, text_message):
    intent_data = {"description": "оплата за рейс", "merchant": "Client A"}

    result = await skill.execute(text_message, sample_context, intent_data)

    assert "Не удалось определить сумму дохода" in result.response_text


# ---------------------------------------------------------------------------
# 2. No categories → error message
# ---------------------------------------------------------------------------
async def test_no_categories_returns_error(sample_context, text_message):
    empty_ctx = SessionContext(
        user_id=sample_context.user_id,
        family_id=sample_context.family_id,
        role=sample_context.role,
        language=sample_context.language,
        currency="USD",
        business_type=sample_context.business_type,
        categories=[],
        merchant_mappings=sample_context.merchant_mappings,
    )
    intent_data = {"amount": 500.0, "description": "оплата"}

    result = await skill.execute(text_message, empty_ctx, intent_data)

    assert "Не нашёл подходящую категорию дохода" in result.response_text


# ---------------------------------------------------------------------------
# 3. Saves income with description, response includes it
# ---------------------------------------------------------------------------
async def test_saves_income_with_description(sample_context, text_message):
    income_cat = {
        "id": str(uuid.uuid4()),
        "name": "Доход",
        "scope": "business",
        "icon": "💰",
    }
    ctx_with_income = SessionContext(
        user_id=sample_context.user_id,
        family_id=sample_context.family_id,
        role=sample_context.role,
        language=sample_context.language,
        currency="USD",
        business_type=sample_context.business_type,
        categories=[*sample_context.categories, income_cat],
        merchant_mappings=sample_context.merchant_mappings,
    )
    intent_data = {
        "amount": 2500.0,
        "description": "оплата за рейс Чикаго",
        "merchant": "Logistics Corp",
        "scope": "business",
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
            "src.skills.add_income.handler.get_session",
            return_value=mock_session,
        ),
        patch("src.skills.add_income.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(text_message, ctx_with_income, intent_data)

    assert mock_session.add.called
    assert mock_session.commit.called
    assert "2500" in result.response_text


# ---------------------------------------------------------------------------
# 4. Finds "Доход" category by name
# ---------------------------------------------------------------------------
async def test_finds_income_category_by_name(sample_context, text_message):
    income_cat_id = str(uuid.uuid4())
    income_cat = {"id": income_cat_id, "name": "Доход", "scope": "family", "icon": "💰"}

    ctx_with_income = SessionContext(
        user_id=sample_context.user_id,
        family_id=sample_context.family_id,
        role=sample_context.role,
        language=sample_context.language,
        currency="USD",
        business_type=sample_context.business_type,
        categories=[*sample_context.categories, income_cat],
        merchant_mappings=sample_context.merchant_mappings,
    )

    intent_data = {
        "amount": 1000.0,
        "description": "зарплата",
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
            "src.skills.add_income.handler.get_session",
            return_value=mock_session,
        ),
        patch("src.skills.add_income.handler.log_action", new_callable=AsyncMock),
    ):
        await skill.execute(text_message, ctx_with_income, intent_data)

    saved_obj = mock_session.add.call_args[0][0]
    assert str(saved_obj.category_id) == income_cat_id


# ---------------------------------------------------------------------------
# 5. Asks user to choose when no income category can be resolved safely
# ---------------------------------------------------------------------------
async def test_unknown_income_category_asks_user_to_choose(sample_context, text_message):
    # sample_context categories are Дизель, Ремонт, Продукты — none is income keyword
    intent_data = {
        "amount": 300.0,
        "description": "перевод",
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
            "src.skills.add_income.handler.get_session",
            return_value=mock_session,
        ),
        patch("src.skills.add_income.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(text_message, sample_context, intent_data)

    assert not mock_session.add.called
    assert "Укажите категорию дохода точнее" in result.response_text
    assert result.buttons is None
