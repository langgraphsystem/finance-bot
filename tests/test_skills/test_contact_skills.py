"""Tests for contact/CRM skills (add, list, find)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.add_contact.handler import AddContactSkill
from src.skills.find_contact.handler import FindContactSkill
from src.skills.list_contacts.handler import ListContactsSkill


def _make_context(**kwargs):
    defaults = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "role": "owner",
        "language": "en",
        "currency": "USD",
        "business_type": None,
        "categories": [],
        "merchant_mappings": [],
    }
    defaults.update(kwargs)
    return SessionContext(**defaults)


def _make_message(text="add client John 917-555-1234"):
    return IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text)


async def test_add_contact_with_name():
    skill = AddContactSkill()
    ctx = _make_context()
    msg = _make_message()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    with patch(
        "src.skills.add_contact.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(
            msg, ctx, {"contact_name": "John Smith", "contact_phone": "917-555-1234"}
        )

    assert "John Smith" in result.response_text
    mock_session.add.assert_called_once()


async def test_add_contact_no_name():
    skill = AddContactSkill()
    ctx = _make_context()
    msg = _make_message("")

    result = await skill.execute(msg, ctx, {})
    assert "name" in result.response_text.lower()


async def test_list_contacts_empty():
    skill = ListContactsSkill()
    ctx = _make_context()
    msg = _make_message("my contacts")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.list_contacts.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(msg, ctx, {})

    assert "no contacts" in result.response_text.lower()


async def test_find_contact_empty_query():
    skill = FindContactSkill()
    ctx = _make_context()
    msg = _make_message("")
    msg.text = ""

    result = await skill.execute(msg, ctx, {})
    assert "who" in result.response_text.lower() or "looking" in result.response_text.lower()


async def test_find_contact_no_results():
    skill = FindContactSkill()
    ctx = _make_context()
    msg = _make_message("find John")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.find_contact.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(msg, ctx, {"contact_name": "John"})

    assert "no contacts" in result.response_text.lower()


async def test_add_contact_system_prompt():
    skill = AddContactSkill()
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "contact" in prompt.lower() or "crm" in prompt.lower()
