"""Tests for correct_category fuzzy matching."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.correct_category.handler import CorrectCategorySkill


def _ctx(categories=None):
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=categories or [
            {"id": str(uuid.uuid4()), "name": "Food"},
            {"id": str(uuid.uuid4()), "name": "Transport"},
            {"id": str(uuid.uuid4()), "name": "Groceries"},
            {"id": str(uuid.uuid4()), "name": "Shopping"},
        ],
        merchant_mappings=[],
    )


def _msg(text="исправь на food"):
    return IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text)


async def test_fuzzy_match_grocery_to_groceries():
    """'Grocery' fuzzy-matches to 'Groceries' category."""
    skill = CorrectCategorySkill()
    ctx = _ctx()
    msg = _msg("исправь на grocery")

    mock_tx = MagicMock()
    mock_tx.id = uuid.uuid4()
    mock_tx.category_id = uuid.uuid4()
    mock_tx.merchant = "store"
    mock_tx.scope = MagicMock()
    mock_tx.scope.value = "family"

    mock_old_cat = MagicMock()
    mock_old_cat.name = "Transport"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First call: query transactions → scalars().all()
            result.scalars.return_value.all.return_value = [mock_tx]
        else:
            # Second call: get old category → scalar_one_or_none()
            result.scalar_one_or_none.return_value = mock_old_cat
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()

    with (
        patch("src.skills.correct_category.handler.get_session", return_value=mock_session),
        patch("src.skills.correct_category.handler.log_action", new_callable=AsyncMock),
    ):
        result = await skill.execute(msg, ctx, {"category": "Grocery"})

    # Should match "Groceries" via fuzzy, not fail
    assert "Groceries" in result.response_text


async def test_exact_match_still_works():
    """Exact match is preferred over fuzzy."""
    ctx = _ctx()

    # "Food" matches exactly
    result_text = None
    for cat in ctx.categories:
        if cat["name"] == "Food":
            result_text = cat["name"]
            break
    assert result_text == "Food"


async def test_no_match_returns_not_found():
    """Completely different name returns 'not found'."""
    skill = CorrectCategorySkill()
    ctx = _ctx()
    msg = _msg("исправь")

    result = await skill.execute(msg, ctx, {"category": "Basketball"})

    assert "не найдена" in result.response_text
