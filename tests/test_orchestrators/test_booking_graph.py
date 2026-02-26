"""Tests for the booking LangGraph orchestrator."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.orchestrators.booking.graph import BookingOrchestrator


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


def _make_message(text="book a hotel in Barcelona"):
    return IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text=text,
    )


async def test_is_hotel_request_positive():
    """Hotel keywords should be detected."""
    assert BookingOrchestrator._is_hotel_request("find hotel in NYC", {})
    assert BookingOrchestrator._is_hotel_request("забронируй отель", {})
    assert BookingOrchestrator._is_hotel_request("booking.com search", {})
    assert BookingOrchestrator._is_hotel_request("", {"hotel_city": "NYC"})


async def test_is_hotel_request_negative():
    """Non-hotel requests should not match."""
    assert not BookingOrchestrator._is_hotel_request("book a haircut", {})
    assert not BookingOrchestrator._is_hotel_request("schedule meeting", {})


async def test_non_hotel_booking_uses_agent_router():
    """Non-hotel booking intents go through AgentRouter."""
    mock_router = AsyncMock()
    mock_router.route = AsyncMock(
        return_value=AsyncMock(response_text="Booking created.")
    )

    orch = BookingOrchestrator(agent_router=mock_router)
    ctx = _make_context()
    msg = _make_message("book a haircut at 3pm")

    result = await orch.invoke("create_booking", msg, ctx, {})
    mock_router.route.assert_called_once()
    assert "Booking created" in result.response_text


async def test_hotel_booking_starts_graph():
    """Hotel booking requests should invoke the LangGraph."""
    orch = BookingOrchestrator(agent_router=AsyncMock())

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "type": "platform_selection",
        "preview_text": "Hotels in Barcelona...",
        "platforms": ["booking.com", "airbnb.com"],
    }

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "__interrupt__": [interrupt_obj],
        })
        ctx = _make_context()
        msg = _make_message("find a hotel in Barcelona for March 15-18")

        result = await orch.invoke("create_booking", msg, ctx, {})

    assert "Barcelona" in result.response_text
    assert result.buttons is not None
    assert any("booking.com" in b["text"] for b in result.buttons)
    assert any("graph_resume:" in b["callback"] for b in result.buttons)


async def test_booking_graph_fallback_on_error():
    """If graph fails, fall back to AgentRouter."""
    mock_router = AsyncMock()
    mock_router.route = AsyncMock(
        return_value=AsyncMock(response_text="Fallback booking.")
    )

    orch = BookingOrchestrator(agent_router=mock_router)

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph broke"))
        ctx = _make_context()
        msg = _make_message("book hotel in Paris")

        await orch.invoke("create_booking", msg, ctx, {})

    mock_router.route.assert_called_once()


async def test_booking_resume():
    """Resume should invoke graph with Command."""
    orch = BookingOrchestrator()

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "response_text": "Searching booking.com...",
            "buttons": [],
        })

        result = await orch.resume("booking-abc-123", "booking.com")

    assert "Searching" in result.response_text


async def test_booking_resume_error():
    """Resume errors should be handled gracefully."""
    orch = BookingOrchestrator()

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("db down"))

        result = await orch.resume("booking-abc-123", "yes")

    assert "Error" in result.response_text


async def test_login_interrupt_buttons():
    """Login interrupt should include login URL and Ready buttons."""
    orch = BookingOrchestrator()

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "type": "login_required",
        "site": "booking.com",
        "login_url": "https://booking.com/login",
        "message": "Please log in to booking.com.",
    }

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "__interrupt__": [interrupt_obj],
        })
        ctx = _make_context()
        msg = _make_message("hotel in Rome")

        result = await orch.invoke("create_booking", msg, ctx, {})

    assert result.buttons is not None
    urls = [b.get("url", "") for b in result.buttons]
    callbacks = [b.get("callback", "") for b in result.buttons]
    assert any("booking.com" in u for u in urls)
    assert any("Ready" in b["text"] for b in result.buttons)
    assert any("graph_resume:" in c for c in callbacks)


async def test_confirm_interrupt_buttons():
    """Confirmation interrupt should show Confirm/Back/Cancel buttons."""
    orch = BookingOrchestrator()

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "type": "booking_confirmation",
        "hotel": {"name": "Grand Hotel"},
        "confirmation_text": "Book Grand Hotel for $200/night?",
    }

    with patch(
        "src.orchestrators.booking.graph._booking_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value={
            "__interrupt__": [interrupt_obj],
        })
        ctx = _make_context()
        msg = _make_message("book hotel in NYC")

        result = await orch.invoke("create_booking", msg, ctx, {})

    assert result.buttons is not None
    texts = [b["text"] for b in result.buttons]
    assert "Confirm" in texts
    assert "Back to results" in texts
    assert "Cancel" in texts


async def test_other_booking_intents_use_agent_router():
    """list_bookings, cancel_booking etc should go through AgentRouter."""
    mock_router = AsyncMock()
    mock_router.route = AsyncMock(
        return_value=AsyncMock(response_text="No bookings found.")
    )

    orch = BookingOrchestrator(agent_router=mock_router)
    ctx = _make_context()
    msg = _make_message("show my bookings")

    await orch.invoke("list_bookings", msg, ctx, {})
    mock_router.route.assert_called_once()
