"""Tests for shopping list skills."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.shopping_list.handler import (
    ShoppingListAddSkill,
    ShoppingListClearSkill,
    ShoppingListRemoveSkill,
    ShoppingListViewSkill,
    _parse_items,
    _parse_list_name,
)


@pytest.fixture
def add_skill():
    return ShoppingListAddSkill()


@pytest.fixture
def view_skill():
    return ShoppingListViewSkill()


@pytest.fixture
def remove_skill():
    return ShoppingListRemoveSkill()


@pytest.fixture
def clear_skill():
    return ShoppingListClearSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg-123",
        chat_id="chat-123",
        type=MessageType.text,
        text=text,
    )


# ─── Unit tests for parsing helpers ──────────────────────────────


def test_parse_list_name_default():
    assert _parse_list_name({}) == "grocery"


def test_parse_list_name_from_intent_data():
    assert _parse_list_name({"shopping_list_name": "Hardware"}) == "hardware"


def test_parse_list_name_strips_and_lowercases():
    assert _parse_list_name({"shopping_list_name": "  Pharmacy  "}) == "pharmacy"


def test_parse_items_from_intent_data():
    items = _parse_items({"shopping_items": ["milk", "eggs", "bread"]}, "")
    assert items == ["milk", "eggs", "bread"]


def test_parse_items_from_text_with_commas():
    items = _parse_items({}, "add milk, eggs, and bread to my list")
    assert len(items) >= 3
    assert any("milk" in i for i in items)
    assert any("eggs" in i for i in items)
    assert any("bread" in i for i in items)


def test_parse_items_empty():
    items = _parse_items({}, "")
    assert items == []


def test_parse_items_filters_empty_strings():
    items = _parse_items({"shopping_items": ["milk", "", "  ", "eggs"]}, "")
    assert items == ["milk", "eggs"]


# ─── Add skill tests ─────────────────────────────────────────────


def _mock_shopping_list(list_id=None, name="grocery"):
    sl = MagicMock()
    sl.id = list_id or uuid.uuid4()
    sl.name = name
    return sl


def _mock_item(name, is_checked=False, item_id=None):
    item = MagicMock()
    item.id = item_id or uuid.uuid4()
    item.name = name
    item.is_checked = is_checked
    item.quantity = None
    item.created_at = datetime.now(UTC)
    return item


@pytest.mark.asyncio
async def test_add_single_item(add_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler.async_session",
        ) as mock_session_factory,
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=[],  # no existing items
        ),
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await add_skill.execute(
            _msg("add milk to my list"),
            ctx,
            {"shopping_items": ["milk"]},
        )

    assert "milk" in result.response_text.lower()
    assert "1 items total" in result.response_text


@pytest.mark.asyncio
async def test_add_multiple_items(add_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler.async_session",
        ) as mock_session_factory,
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=[],  # no existing items
        ),
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await add_skill.execute(
            _msg("add milk, eggs, bread"),
            ctx,
            {"shopping_items": ["milk", "eggs", "bread"]},
        )

    assert "3 items" in result.response_text
    assert "3 items total" in result.response_text


@pytest.mark.asyncio
async def test_add_empty_items_asks(add_skill, ctx):
    result = await add_skill.execute(_msg("add to my list"), ctx, {})
    assert "what" in result.response_text.lower()


@pytest.mark.asyncio
async def test_add_skips_duplicate_item(add_skill, ctx):
    """When item already exists on list, skip it and report."""
    list_id = uuid.uuid4()
    existing = [_mock_item("хлеб"), _mock_item("молоко")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=existing,
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await add_skill.execute(
            _msg("добавь хлеб и масло"),
            ctx,
            {"shopping_items": ["хлеб", "масло"]},
        )

    assert "масло" in result.response_text.lower()
    assert "already on list" in result.response_text.lower()
    assert "хлеб" in result.response_text.lower()


@pytest.mark.asyncio
async def test_add_all_duplicates_reports(add_skill, ctx):
    """When ALL items are duplicates, return message without inserting."""
    list_id = uuid.uuid4()
    existing = [_mock_item("хлеб"), _mock_item("соль")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=existing,
        ),
    ):
        result = await add_skill.execute(
            _msg("добавь хлеб"),
            ctx,
            {"shopping_items": ["хлеб"]},
        )

    assert "already on your list" in result.response_text.lower()


@pytest.mark.asyncio
async def test_add_dedup_within_batch(add_skill, ctx):
    """Don't add the same item twice within a single message."""
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await add_skill.execute(
            _msg("add bread, bread, milk"),
            ctx,
            {"shopping_items": ["bread", "bread", "milk"]},
        )

    # Only 2 unique items should be added, not 3
    assert "2 items" in result.response_text
    assert "already on list" in result.response_text.lower()


@pytest.mark.asyncio
async def test_add_to_named_list(add_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_or_create_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id, name="hardware"),
        ),
        patch(
            "src.skills.shopping_list.handler.async_session",
        ) as mock_session_factory,
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=[],  # no existing items
        ),
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await add_skill.execute(
            _msg("add nails to my hardware list"),
            ctx,
            {"shopping_items": ["nails"], "shopping_list_name": "hardware"},
        )

    assert "hardware" in result.response_text.lower()


# ─── View skill tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_empty_list(view_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_all_items",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await view_skill.execute(_msg("show my list"), ctx, {})

    assert "empty" in result.response_text.lower()


@pytest.mark.asyncio
async def test_view_no_lists(view_skill, ctx):
    with patch(
        "src.skills.shopping_list.handler._get_most_recent_list",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await view_skill.execute(_msg("show my list"), ctx, {})

    assert "no lists" in result.response_text.lower()


@pytest.mark.asyncio
async def test_view_list_with_items(view_skill, ctx):
    list_id = uuid.uuid4()
    items = [
        _mock_item("milk"),
        _mock_item("eggs"),
        _mock_item("bread", is_checked=True),
    ]
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_all_items",
            new_callable=AsyncMock,
            return_value=items,
        ),
    ):
        result = await view_skill.execute(_msg("what's on my list?"), ctx, {})

    assert "2 items" in result.response_text
    assert "milk" in result.response_text.lower()
    assert "eggs" in result.response_text.lower()
    assert "Checked off: 1" in result.response_text


# ─── Remove skill tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_no_lists(remove_skill, ctx):
    with patch(
        "src.skills.shopping_list.handler._get_most_recent_list",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await remove_skill.execute(_msg("got the milk"), ctx, {})

    assert "no lists" in result.response_text.lower()


@pytest.mark.asyncio
async def test_remove_empty_list(remove_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await remove_skill.execute(_msg("got the milk"), ctx, {})

    assert "already empty" in result.response_text.lower()


@pytest.mark.asyncio
async def test_remove_got_everything(remove_skill, ctx):
    list_id = uuid.uuid4()
    items = [_mock_item("milk"), _mock_item("eggs")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=items,
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await remove_skill.execute(_msg("got everything"), ctx, {})

    assert "2 items" in result.response_text
    assert "all done" in result.response_text.lower()


@pytest.mark.asyncio
async def test_remove_specific_item(remove_skill, ctx):
    list_id = uuid.uuid4()
    items = [_mock_item("milk"), _mock_item("eggs")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=items,
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await remove_skill.execute(
            _msg("got the milk"),
            ctx,
            {"shopping_items": ["milk"]},
        )

    assert "checked off" in result.response_text.lower()
    assert "1 remaining" in result.response_text


@pytest.mark.asyncio
async def test_remove_item_not_found(remove_skill, ctx):
    list_id = uuid.uuid4()
    items = [_mock_item("milk"), _mock_item("eggs")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_unchecked_items",
            new_callable=AsyncMock,
            return_value=items,
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await remove_skill.execute(
            _msg("got the butter"),
            ctx,
            {"shopping_items": ["butter"]},
        )

    assert "didn't find" in result.response_text.lower()


# ─── Clear skill tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_no_lists(clear_skill, ctx):
    with patch(
        "src.skills.shopping_list.handler._get_most_recent_list",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await clear_skill.execute(_msg("clear my list"), ctx, {})

    assert "no lists" in result.response_text.lower()


@pytest.mark.asyncio
async def test_clear_empty_list(clear_skill, ctx):
    list_id = uuid.uuid4()
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_all_items",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await clear_skill.execute(_msg("clear my list"), ctx, {})

    assert "already empty" in result.response_text.lower()


@pytest.mark.asyncio
async def test_clear_list_with_items(clear_skill, ctx):
    list_id = uuid.uuid4()
    items = [_mock_item("milk"), _mock_item("eggs"), _mock_item("bread")]
    with (
        patch(
            "src.skills.shopping_list.handler._get_most_recent_list",
            new_callable=AsyncMock,
            return_value=_mock_shopping_list(list_id),
        ),
        patch(
            "src.skills.shopping_list.handler._get_all_items",
            new_callable=AsyncMock,
            return_value=items,
        ),
        patch("src.skills.shopping_list.handler.async_session") as mock_session_factory,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await clear_skill.execute(_msg("clear my list"), ctx, {})

    assert "cleared" in result.response_text.lower()
    assert "3 items" in result.response_text


# ─── System prompt tests ─────────────────────────────────────────


def test_system_prompt_includes_language(add_skill, ctx):
    prompt = add_skill.get_system_prompt(ctx)
    assert "en" in prompt


def test_system_prompt_default_language(add_skill):
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language=None,
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    prompt = add_skill.get_system_prompt(ctx)
    assert "en" in prompt


# ─── Skill attribute tests ───────────────────────────────────────


def test_add_skill_attributes(add_skill):
    assert add_skill.name == "shopping_list_add"
    assert add_skill.intents == ["shopping_list_add"]
    assert add_skill.model == "claude-haiku-4-5"


def test_view_skill_attributes(view_skill):
    assert view_skill.name == "shopping_list_view"
    assert view_skill.intents == ["shopping_list_view"]


def test_remove_skill_attributes(remove_skill):
    assert remove_skill.name == "shopping_list_remove"
    assert remove_skill.intents == ["shopping_list_remove"]


def test_clear_skill_attributes(clear_skill):
    assert clear_skill.name == "shopping_list_clear"
    assert clear_skill.intents == ["shopping_list_clear"]
