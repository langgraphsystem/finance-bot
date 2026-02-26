"""Booking orchestrator state definition.

Maps the Redis-based FSM steps to a typed LangGraph state.
"""

from typing import Any, TypedDict


class BookingState(TypedDict, total=False):
    """State for the hotel booking LangGraph orchestrator.

    Mirrors the Redis ``hotel_booking:{user_id}`` payload but uses
    LangGraph checkpointer for persistence instead of Redis TTL.
    """

    # Identity
    user_id: str
    family_id: str
    language: str

    # Flow control
    step: str  # Current FSM step name
    task: str  # Original user request text
    error: str  # Error message if any step fails

    # Parsed request (from Gemini Flash)
    parsed: dict[str, Any]
    preview_text: str

    # Platform selection
    site: str  # Domain: booking.com, airbnb.com, etc.

    # Search results
    results: list[dict[str, Any]]
    page: int
    search_url: str

    # Selection
    selected_hotel: dict[str, Any]

    # Booking execution
    booking_data: dict[str, Any]

    # User interaction (from interrupt/resume)
    user_choice: str  # User's response at interrupt points

    # Output
    response_text: str
    buttons: list[dict[str, str]]
