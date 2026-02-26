"""Booking orchestrator graph nodes.

Each node wraps existing functions from ``src/tools/browser_booking``
and uses ``interrupt()`` at points where user interaction is required.

Graph flow::

    parse_request → preview_prices → ask_platform (interrupt)
        → check_auth → [need_login? → ask_login (interrupt) → check_auth]
        → search → present_results (interrupt)
        → [user selects hotel | sort | more | cancel]
        → confirm_selection (interrupt)
        → execute_booking → present_booking_result (interrupt)
        → finalize
"""

import logging
from typing import Any

from langgraph.types import interrupt

logger = logging.getLogger(__name__)


async def parse_request(state: dict[str, Any]) -> dict[str, Any]:
    """Parse the user's natural-language booking request into structured data."""
    from src.tools.browser_booking import parse_booking_request

    task = state.get("task", "")
    language = state.get("language", "en")

    parsed = await parse_booking_request(task, language)
    if not parsed or not parsed.get("city"):
        return {
            "step": "error",
            "error": "parse_failed",
            "response_text": (
                "I need more details to search for hotels.\n\n"
                "Please include: <b>city</b>, <b>dates</b>\n"
                "Example: <i>Find a hotel in Barcelona for March 15-18, "
                "up to $150/night</i>"
            ),
            "buttons": [],
        }

    if not parsed.get("check_in") or not parsed.get("check_out"):
        return {
            "step": "error",
            "error": "missing_dates",
            "parsed": parsed,
            "response_text": (
                f"I'll search hotels in <b>{parsed['city']}</b>, "
                "but I need the <b>dates</b>.\n\n"
                "When do you want to check in and check out?\n"
                "Example: <i>March 15-18</i>"
            ),
            "buttons": [],
        }

    return {"parsed": parsed, "step": "parsed"}


async def preview_prices(state: dict[str, Any]) -> dict[str, Any]:
    """Quick Gemini Grounding price preview."""
    from src.tools.browser_booking import (
        _calc_nights,
        _format_dates,
        _get_price_preview,
    )

    if state.get("step") == "error":
        return {}

    parsed = state.get("parsed", {})
    task = state.get("task", "")
    language = state.get("language", "en")

    preview_text = await _get_price_preview(task, parsed, language)

    nights = _calc_nights(parsed.get("check_in"), parsed.get("check_out"))
    budget_str = ""
    if parsed.get("budget_per_night"):
        budget_str = f"\nBudget: <b>${parsed['budget_per_night']}/night</b>"

    header = (
        f"<b>Hotel Search</b>\n\n"
        f"{parsed['city']}, "
        f"{_format_dates(parsed.get('check_in'), parsed.get('check_out'))}"
        f" ({nights} {'night' if nights == 1 else 'nights'})"
        f"{budget_str}\n\n"
    )

    return {
        "preview_text": header + preview_text,
        "step": "preview_done",
    }


async def ask_platform(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt: ask the user which booking platform to use."""
    from src.tools.browser_booking import _SUPPORTED_PLATFORMS

    if state.get("step") == "error":
        return {}

    preview = state.get("preview_text", "")
    platforms = list(_SUPPORTED_PLATFORMS.keys())

    choice = interrupt({
        "type": "platform_selection",
        "preview_text": preview + "\n\n<i>Select a platform to search:</i>",
        "platforms": platforms,
    })

    if choice == "cancel":
        return {
            "step": "cancelled",
            "response_text": "Hotel search cancelled.",
            "buttons": [],
        }

    return {"site": choice, "step": "platform_selected"}


async def check_auth(state: dict[str, Any]) -> dict[str, Any]:
    """Check if the user has a saved browser session for the selected site."""
    from src.tools import browser_service

    if state.get("step") in ("error", "cancelled"):
        return {}

    site = state.get("site", "")
    user_id = state.get("user_id", "")

    storage = await browser_service.get_storage_state(user_id, site)
    if storage:
        return {"step": "auth_ok"}

    return {"step": "need_login"}


async def ask_login(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt: ask the user to log in via the browser extension."""
    from src.tools import browser_service

    if state.get("step") != "need_login":
        return {}

    site = state.get("site", "")
    login_url = browser_service.get_login_url(site)
    city = state.get("parsed", {}).get("city", "")

    choice = interrupt({
        "type": "login_required",
        "site": site,
        "login_url": login_url,
        "message": (
            f"I need access to <b>{site}</b> to search hotels"
            f"{f' in {city}' if city else ''}.\n\n"
            f"1. Open the link below and log in\n"
            f"2. Click the Finance Bot extension to save your session\n"
            f"3. Come back and tap <b>Ready</b>"
        ),
    })

    if choice == "cancel":
        return {
            "step": "cancelled",
            "response_text": "Hotel search cancelled.",
            "buttons": [],
        }

    # User said "ready" — re-check auth
    return {"step": "login_ready"}


async def search_hotels(state: dict[str, Any]) -> dict[str, Any]:
    """Execute browser search on the selected platform."""
    if state.get("step") in ("error", "cancelled"):
        return {}

    user_id = state.get("user_id", "")
    site = state.get("site", "")
    parsed = state.get("parsed", {})

    # We need to set up a temporary Redis state for the existing
    # browser_booking functions that read from Redis
    from src.tools.browser_booking import _set_state, execute_browser_search

    temp_state = {
        "flow_id": "lg",
        "step": "browser_searching",
        "task": state.get("task", ""),
        "family_id": state.get("family_id", ""),
        "language": state.get("language", "en"),
        "site": site,
        "parsed": parsed,
        "results": [],
        "page": 1,
        "selected_hotel": None,
        "search_url": None,
    }
    await _set_state(user_id, temp_state)

    result = await execute_browser_search(user_id)
    text = result.get("text", "")
    buttons = result.get("buttons", [])
    results = result.get("results", [])

    return {
        "results": results,
        "step": "results_ready",
        "response_text": text,
        "buttons": buttons or [],
        "page": 1,
    }


async def present_results(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt: show search results and wait for user selection."""
    if state.get("step") in ("error", "cancelled"):
        return {}

    results = state.get("results", [])
    if not results:
        return {
            "step": "error",
            "error": "no_results",
            "response_text": "No hotels found. Try different dates or city.",
            "buttons": [],
        }

    choice = interrupt({
        "type": "hotel_selection",
        "response_text": state.get("response_text", ""),
        "buttons": state.get("buttons", []),
        "result_count": len(results),
    })

    if choice == "cancel":
        return {
            "step": "cancelled",
            "response_text": "Hotel search cancelled.",
            "buttons": [],
        }

    if choice.startswith("sort:"):
        sort_type = choice.split(":", 1)[1]
        return {"step": "needs_resort", "user_choice": sort_type}

    if choice == "more":
        return {"step": "needs_more", "page": state.get("page", 1) + 1}

    # User selected a hotel by index
    try:
        idx = int(choice)
        if 0 <= idx < len(results):
            return {
                "selected_hotel": results[idx],
                "step": "hotel_selected",
            }
    except (ValueError, IndexError):
        pass

    return {"step": "hotel_selected", "user_choice": choice}


async def confirm_selection(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt: confirm the selected hotel before booking."""
    if state.get("step") in ("error", "cancelled"):
        return {}

    hotel = state.get("selected_hotel", {})
    if not hotel:
        return {"step": "results_ready"}

    from src.tools.browser_booking import _format_confirmation_telegram

    text = _format_confirmation_telegram(hotel, state.get("parsed", {}))

    choice = interrupt({
        "type": "booking_confirmation",
        "hotel": hotel,
        "confirmation_text": text,
    })

    if choice == "cancel":
        return {
            "step": "cancelled",
            "response_text": "Hotel search cancelled.",
            "buttons": [],
        }

    if choice == "back":
        return {"step": "results_ready"}

    if choice in ("yes", "confirm"):
        return {"step": "confirmed"}

    return {"step": "results_ready"}


async def execute_booking_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the actual browser booking on the hotel site."""
    if state.get("step") != "confirmed":
        return {}

    user_id = state.get("user_id", "")

    # Use existing function which reads from Redis
    from src.tools.browser_booking import execute_booking

    result = await execute_booking(user_id)
    text = result.get("text", "")
    buttons = result.get("buttons", [])
    booking_data = result.get("booking_data", {})

    return {
        "booking_data": booking_data,
        "response_text": text,
        "buttons": buttons or [],
        "step": "booking_done",
    }


async def finalize(state: dict[str, Any]) -> dict[str, Any]:
    """Clean up and return final result."""
    from src.tools.browser_booking import _clear_state

    user_id = state.get("user_id", "")
    await _clear_state(user_id)

    return {
        "step": "done",
        "response_text": state.get("response_text", "Booking flow complete."),
    }


# ── Routing functions ────────────────────────────────────────────────────────


def route_after_auth(state: dict[str, Any]) -> str:
    """Route after auth check: search if OK, login if not."""
    step = state.get("step", "")
    if step == "auth_ok":
        return "search"
    if step == "need_login":
        return "ask_login"
    return "finalize"


def route_after_login(state: dict[str, Any]) -> str:
    """Route after login interrupt: re-check auth or finalize."""
    step = state.get("step", "")
    if step == "login_ready":
        return "check_auth"
    return "finalize"


def route_after_results(state: dict[str, Any]) -> str:
    """Route after user interacts with results."""
    step = state.get("step", "")
    if step == "hotel_selected":
        return "confirm_selection"
    if step in ("needs_resort", "needs_more"):
        return "search"
    if step == "cancelled":
        return "finalize"
    return "finalize"


def route_after_confirm(state: dict[str, Any]) -> str:
    """Route after confirmation: book or go back."""
    step = state.get("step", "")
    if step == "confirmed":
        return "execute_booking"
    if step == "results_ready":
        return "present_results"
    return "finalize"


def should_continue(state: dict[str, Any]) -> str:
    """Check if flow should continue or abort."""
    step = state.get("step", "")
    if step in ("error", "cancelled", "done"):
        return "end"
    return "continue"
