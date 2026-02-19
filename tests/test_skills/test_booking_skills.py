"""Tests for booking skills (create, list, cancel, reschedule)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.cancel_booking.handler import CancelBookingSkill
from src.skills.create_booking.handler import CreateBookingSkill
from src.skills.list_bookings.handler import ListBookingsSkill
from src.skills.reschedule_booking.handler import RescheduleBookingSkill


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
        "timezone": "America/New_York",
    }
    defaults.update(kwargs)
    return SessionContext(**defaults)


def _make_message(text="book John tomorrow 2pm"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text, text=text
    )


async def test_create_booking_with_title():
    skill = CreateBookingSkill()
    ctx = _make_context()
    msg = _make_message("faucet repair for John")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    with patch(
        "src.skills.create_booking.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(
            msg, ctx, {"booking_title": "faucet repair", "contact_name": ""}
        )

    assert "faucet repair" in result.response_text.lower()


async def test_create_booking_no_title():
    skill = CreateBookingSkill()
    ctx = _make_context()
    msg = _make_message("")
    msg.text = ""

    result = await skill.execute(msg, ctx, {})
    assert "what" in result.response_text.lower() or "book" in result.response_text.lower()


async def test_list_bookings_empty():
    skill = ListBookingsSkill()
    ctx = _make_context()
    msg = _make_message("my schedule today")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.list_bookings.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(msg, ctx, {"period": "today"})

    assert "clear" in result.response_text.lower() or "no" in result.response_text.lower()


async def test_cancel_booking_not_found():
    skill = CancelBookingSkill()
    ctx = _make_context()
    msg = _make_message("cancel John's appointment")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "src.skills.cancel_booking.handler.async_session",
        return_value=mock_session,
    ):
        result = await skill.execute(msg, ctx, {"contact_name": "John"})

    assert "no" in result.response_text.lower()


async def test_reschedule_booking_no_time():
    skill = RescheduleBookingSkill()
    ctx = _make_context()
    msg = _make_message("move John to later")

    result = await skill.execute(msg, ctx, {})
    assert "when" in result.response_text.lower()


async def test_create_booking_system_prompt():
    skill = CreateBookingSkill()
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "booking" in prompt.lower() or "appointment" in prompt.lower()


async def test_list_bookings_system_prompt():
    skill = ListBookingsSkill()
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "booking" in prompt.lower()
