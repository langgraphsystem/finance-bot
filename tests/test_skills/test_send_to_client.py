"""Tests for send_to_client skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.send_to_client.handler import SendToClientSkill


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


def _make_message(text="text John I'm running late"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


async def test_send_to_client_no_name():
    skill = SendToClientSkill()
    ctx = _make_context()
    msg = _make_message("send message")

    result = await skill.execute(msg, ctx, {})
    assert "who" in result.response_text.lower()


async def test_send_to_client_contact_not_found():
    skill = SendToClientSkill()
    ctx = _make_context()
    msg = _make_message("text John I'm late")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.send_to_client.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(msg, ctx, {"contact_name": "John"})

    assert "no contact" in result.response_text.lower()


async def test_send_to_client_with_contact():
    skill = SendToClientSkill()
    ctx = _make_context()
    msg = _make_message("text John I'm running late")

    mock_contact = MagicMock()
    mock_contact.id = uuid.uuid4()
    mock_contact.name = "John Smith"
    mock_contact.phone = "917-555-1234"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_contact
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.send_to_client.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(
            msg, ctx, {"contact_name": "John", "description": "I'm running late"}
        )

    assert "John Smith" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 3  # SMS, Call, Cancel


async def test_send_to_client_system_prompt():
    skill = SendToClientSkill()
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "client" in prompt.lower()
