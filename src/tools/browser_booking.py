"""Multi-step hotel booking flow via Telegram with real browser automation.

Flow:
1. Parse user request (Gemini Flash) → {city, dates, guests, budget, ...}
2. Gemini Grounding preview — quick price overview (2-3 sec)
3. User selects booking platform → auth check
4. If no session → send login URL + extension instructions
5. Browser-Use navigates real site → search, filter, extract results
6. User selects hotel / adjusts filters / views more
7. Browser-Use books hotel → stops before payment
8. If no payment → confirm. If payment → send URL for manual completion.

States: platform_selection → awaiting_login → browser_searching →
        awaiting_selection → confirming → browser_booking →
        payment_handoff → done

Redis key: hotel_booking:{user_id} (TTL 900s)
"""

import json
import logging
import re
import uuid
from typing import Any

from src.core.db import redis

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

FLOW_TTL = 900  # 15 minutes
_REDIS_PREFIX = "hotel_booking"

SEARCH_MAX_STEPS = 30
SEARCH_TIMEOUT = 180  # 3 minutes
FILTER_MAX_STEPS = 15
FILTER_TIMEOUT = 90
BOOKING_MAX_STEPS = 25
BOOKING_TIMEOUT = 120  # 2 minutes
MAX_RESULTS = 5

_SUPPORTED_PLATFORMS = {
    "booking.com": "https://www.booking.com",
    "airbnb.com": "https://www.airbnb.com",
    "hotels.com": "https://www.hotels.com",
    "expedia.com": "https://www.expedia.com",
    "agoda.com": "https://www.agoda.com",
    "ostrovok.ru": "https://ostrovok.ru",
}

# ── Prompts ──────────────────────────────────────────────────────────────────

_PARSE_REQUEST_PROMPT = """\
Extract hotel booking details from this message. Return ONLY valid JSON, no text.

Message: "{task}"
Today's date: {today}

Return:
{{"city": "city name in English",
  "check_in": "YYYY-MM-DD",
  "check_out": "YYYY-MM-DD",
  "guests": 2,
  "budget_per_night": null or number,
  "currency": "USD",
  "amenities": [],
  "star_rating": null or number,
  "distance_from": null or "landmark name",
  "sort_by": "best_value"}}

Rules:
- If dates are relative ("next week", "завтра"), calculate from today
- If only duration given ("на 3 ночи"), set check_in to tomorrow
- Default guests=2 if not specified
- Keep budget as number only (no currency symbol)
- Detect language and translate city to English
- If info is missing, set to null"""

_PREVIEW_PROMPT = """\
Find current hotel prices for this search: {task}

Return a brief overview in {language}:
- Price range (cheapest to most expensive)
- Average price per night
- Best time to book tip (if relevant)
- 2-3 notable hotels with prices

Keep it concise — 5-7 lines. Use numbers and prices."""

_SEARCH_TASK_PROMPT = """\
Go to {site_url} and search for hotels:

DESTINATION: {city}
CHECK-IN: {check_in}
CHECK-OUT: {check_out}
GUESTS: {guests} adults
{filter_section}

Steps:
1. Navigate to {site_url}
2. Enter the destination "{city}" in the search box
3. Set check-in date to {check_in} and check-out date to {check_out}
4. Set {guests} adults, 0 children
5. Click Search
6. Wait for results to load fully
{filter_steps}
7. Extract the top {max_results} hotel results visible on the page

For EACH hotel, extract ALL of the following and return as a JSON array:
[{{"name": "Hotel Name",
   "price_per_night": "$135",
   "total_price": "$405",
   "rating": "8.9",
   "review_count": "2341",
   "distance": "1.2 km from center",
   "amenities": ["pool", "wifi", "parking"],
   "cancellation": "Free cancellation until March 13",
   "description": "Brief location/feature description"}}]

IMPORTANT:
- Stay on the search results page. Do NOT click on individual hotels.
- Extract real prices shown on the page (not estimated).
- If a CAPTCHA appears, STOP and return exactly: CAPTCHA_DETECTED
- If the site asks to log in or sign in, STOP and return exactly: LOGIN_REQUIRED
- If no results are found, return exactly: NO_RESULTS"""

_FILTER_TASK_PROMPT = """\
You are on {site_url} looking at hotel search results for "{city}".

Apply these changes to the current search:
{changes}

After applying, wait for results to reload, then extract the top {max_results} \
results in the same JSON array format as before.

If the page needs to reload after applying filters, wait for it to complete."""

_BOOKING_TASK_PROMPT = """\
Book this hotel on {site_url}:

Hotel: {hotel_name}
Check-in: {check_in}
Check-out: {check_out}
Guests: {guests}

Steps:
1. Navigate to the hotel page or find it in search results
2. Select the cheapest available room (or "{room_type}" if specified)
3. Click "Reserve" / "Book" / "Select"
4. On the booking form:
   - Check if personal details are pre-filled from the account
   - Fill in any required fields if possible
   - Note the total price and cancellation policy
5. Check if payment is required now or can be paid at the hotel
6. DO NOT click the final "Complete Booking" / "Confirm" button yet

Return a JSON object:
{{"status": "READY_TO_BOOK" or "PAYMENT_REQUIRED" or "SOLD_OUT" or "LOGIN_REQUIRED",
  "final_price": "$405",
  "price_per_night": "$135",
  "cancellation_policy": "Free cancellation until March 13",
  "payment_type": "pay_at_hotel" or "prepay_required",
  "saved_card": "Visa ending 4242" or null,
  "room_type": "Superior Double Room",
  "booking_url": "current page URL",
  "notes": "any important details"}}

IMPORTANT:
- If payment card entry is required, report PAYMENT_REQUIRED with the booking_url.
- If the hotel is sold out, report SOLD_OUT.
- If session expired, report LOGIN_REQUIRED."""

_CONFIRM_BOOKING_PROMPT = """\
Complete the hotel booking on {site_url}.

Click the final "Complete Booking" / "Book Now" / "Confirm Reservation" button.

After clicking, wait for the confirmation page to load.

Extract and return:
{{"confirmation_number": "...",
  "hotel_name": "...",
  "check_in": "...",
  "check_out": "...",
  "total_price": "...",
  "cancellation_policy": "...",
  "special_instructions": "..."}}

If the booking fails or an error appears, describe what happened."""


# ── Redis Helpers ────────────────────────────────────────────────────────────


async def get_booking_state(user_id: str) -> dict | None:
    """Get the current hotel booking flow state from Redis."""
    raw = await redis.get(f"{_REDIS_PREFIX}:{user_id}")
    if not raw:
        return None
    return json.loads(raw)


async def _set_state(user_id: str, state: dict) -> None:
    """Store hotel booking flow state in Redis."""
    await redis.set(
        f"{_REDIS_PREFIX}:{user_id}",
        json.dumps(state, ensure_ascii=False, default=str),
        ex=FLOW_TTL,
    )


async def _clear_state(user_id: str) -> None:
    """Clear hotel booking flow state from Redis."""
    await redis.delete(f"{_REDIS_PREFIX}:{user_id}")


# ── Request Parsing ──────────────────────────────────────────────────────────


async def parse_booking_request(
    task: str, language: str = "en"
) -> dict[str, Any] | None:
    """Parse natural language booking request into structured data via Gemini Flash.

    Returns dict with: city, check_in, check_out, guests, budget_per_night, etc.
    Returns None if parsing fails or essential fields are missing.
    """
    from datetime import date

    from src.core.llm.clients import generate_text

    try:
        prompt = _PARSE_REQUEST_PROMPT.format(
            task=task, today=date.today().isoformat()
        )
        raw = await generate_text(
            "gemini-3-flash-preview",
            "You extract structured data from text. Return only valid JSON.",
            max_tokens=256,
            prompt=prompt,
        )
        parsed = _extract_json_object(raw)
        if not parsed:
            return None

        # Validate minimum fields
        if not parsed.get("city"):
            return None

        # Defaults
        parsed.setdefault("guests", 2)
        parsed.setdefault("currency", "USD")
        parsed.setdefault("amenities", [])
        parsed.setdefault("sort_by", "best_value")

        return parsed
    except Exception as e:
        logger.warning("Failed to parse booking request: %s", e)
        return None


# ── Flow Entry Point ─────────────────────────────────────────────────────────


async def start_flow(
    user_id: str,
    family_id: str,
    task: str,
    language: str = "en",
) -> dict[str, Any]:
    """Start the hotel booking flow.

    1. Parse request with Gemini Flash
    2. Quick Gemini Grounding price preview
    3. Return platform selection buttons

    Returns dict with: text, buttons, parsed (or error).
    """
    # Parse the booking request
    parsed = await parse_booking_request(task, language)
    if not parsed or not parsed.get("city"):
        return {
            "text": (
                "I need more details to search for hotels.\n\n"
                "Please include: <b>city</b>, <b>dates</b>\n"
                "Example: <i>Find a hotel in Barcelona for March 15-18, "
                "up to $150/night</i>"
            ),
            "buttons": None,
        }

    if not parsed.get("check_in") or not parsed.get("check_out"):
        return {
            "text": (
                f"I'll search hotels in <b>{parsed['city']}</b>, "
                "but I need the <b>dates</b>.\n\n"
                "When do you want to check in and check out?\n"
                "Example: <i>March 15-18</i> or <i>на 3 ночи с завтра</i>"
            ),
            "buttons": None,
        }

    # Gemini Grounding quick preview
    preview_text = await _get_price_preview(task, parsed, language)

    # Create flow state
    flow_id = str(uuid.uuid4())[:8]
    state = {
        "flow_id": flow_id,
        "step": "platform_selection",
        "task": task,
        "family_id": family_id,
        "language": language,
        "parsed": parsed,
        "results": [],
        "page": 1,
        "selected_hotel": None,
        "search_url": None,
    }
    await _set_state(user_id, state)

    # Build platform buttons
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

    text = header + preview_text + "\n\n<i>Select a platform to search:</i>"

    buttons = []
    for domain in _SUPPORTED_PLATFORMS:
        buttons.append({
            "text": domain,
            "callback": f"hotel_platform:{flow_id}:{domain}",
        })
    buttons.append({"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"})

    return {"text": text, "buttons": buttons}


async def _get_price_preview(
    task: str, parsed: dict, language: str
) -> str:
    """Quick Gemini Grounding price preview (2-3 seconds)."""
    from google.genai import types

    from src.core.llm.clients import google_client

    try:
        client = google_client()
        prompt = _PREVIEW_PROMPT.format(task=task, language=language)
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        raw = response.text or ""
        return _format_preview_telegram(raw, parsed.get("city", ""))
    except Exception as e:
        logger.warning("Gemini preview failed: %s", e)
        return "<i>Price preview unavailable</i>"


# ── Platform Selection ───────────────────────────────────────────────────────


async def handle_platform_choice(
    user_id: str, platform: str
) -> dict[str, Any]:
    """Handle user's platform selection.

    Returns dict with: action, text, buttons.
    Actions: "search", "need_login", "no_flow", "error"
    """
    state = await get_booking_state(user_id)
    if not state or state.get("step") != "platform_selection":
        return {"action": "no_flow", "text": "No active hotel search."}

    domain = platform.lower().strip()
    if domain not in _SUPPORTED_PLATFORMS:
        return {
            "action": "error",
            "text": f"Platform <b>{domain}</b> is not supported yet.",
        }

    state["site"] = domain
    await _set_state(user_id, state)

    return await check_auth_and_search(user_id)


async def check_auth_and_search(user_id: str) -> dict[str, Any]:
    """Check if user has a saved session, then search or prompt login.

    Returns dict with: action, text, buttons.
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active hotel search."}

    site = state.get("site", "")
    flow_id = state["flow_id"]

    # Check for saved cookies
    storage_state = await browser_service.get_storage_state(user_id, site)

    if storage_state:
        # Has session → start browser search
        state["step"] = "browser_searching"
        await _set_state(user_id, state)
        return await execute_browser_search(user_id)

    # No session → prompt login
    state["step"] = "awaiting_login"
    await _set_state(user_id, state)

    login_url = browser_service.get_login_url(site)
    parsed = state.get("parsed", {})
    city = parsed.get("city", "")

    return {
        "action": "need_login",
        "text": (
            f"I need access to <b>{site}</b> to search hotels"
            f"{f' in {city}' if city else ''}.\n\n"
            f"1. Open the link below and log in\n"
            f"2. Click the Finance Bot extension to save your session\n"
            f"3. Come back and tap <b>Ready</b>\n\n"
            f"Don't have the extension? Send /extension"
        ),
        "buttons": [
            {"text": f"Log in to {site}", "url": login_url},
            {"text": "Ready — check session", "callback": f"hotel_login_ready:{flow_id}"},
            {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
        ],
    }


async def handle_login_ready(user_id: str) -> dict[str, Any]:
    """User claims they've saved session via extension — verify and proceed.

    Returns dict with: action, text, buttons.
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state or state.get("step") != "awaiting_login":
        return {"action": "no_flow", "text": "No active hotel search."}

    site = state.get("site", "")
    flow_id = state["flow_id"]

    storage_state = await browser_service.get_storage_state(user_id, site)
    if not storage_state:
        login_url = browser_service.get_login_url(site)
        return {
            "action": "need_login",
            "text": (
                f"I still don't see a saved session for <b>{site}</b>.\n\n"
                "Make sure you:\n"
                "1. Logged into the site in your browser\n"
                "2. Clicked the Finance Bot extension → Save Session\n\n"
                "Try again when ready."
            ),
            "buttons": [
                {"text": f"Log in to {site}", "url": login_url},
                {"text": "Ready — check again", "callback": f"hotel_login_ready:{flow_id}"},
                {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
            ],
        }

    # Session found → proceed to search
    state["step"] = "browser_searching"
    await _set_state(user_id, state)
    return await execute_browser_search(user_id)


# ── Browser-Use Search ───────────────────────────────────────────────────────


async def execute_browser_search(user_id: str) -> dict[str, Any]:
    """Execute hotel search on real booking site via Browser-Use.

    Returns dict with: action, text, buttons.
    Actions: "results", "login_required", "captcha", "no_results", "error"
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active hotel search."}

    site = state["site"]
    parsed = state.get("parsed", {})
    flow_id = state["flow_id"]
    language = state.get("language", "en")

    # Build search prompt
    prompt = _build_search_prompt(site, parsed)

    # Execute browser-use
    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=site,
        task=prompt,
        max_steps=SEARCH_MAX_STEPS,
        timeout=SEARCH_TIMEOUT,
    )

    raw = result.get("result", "")

    # Check for special statuses
    if "CAPTCHA_DETECTED" in raw:
        search_url = _build_direct_search_url(site, parsed)
        state["step"] = "awaiting_selection"
        await _set_state(user_id, state)
        return {
            "action": "captcha",
            "text": (
                f"<b>{site}</b> is showing a CAPTCHA.\n\n"
                "Please search manually using the link below, "
                "then tell me which hotel you'd like to book."
            ),
            "buttons": [
                {"text": f"Search on {site}", "url": search_url},
                {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
            ],
        }

    if "LOGIN_REQUIRED" in raw:
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await check_auth_and_search(user_id)

    if "NO_RESULTS" in raw:
        return {
            "action": "no_results",
            "text": (
                f"No hotels found on <b>{site}</b> for your criteria.\n\n"
                "Try adjusting your dates or budget."
            ),
            "buttons": [
                {"text": "Change dates", "callback": f"hotel_cancel:{flow_id}"},
            ],
        }

    # Parse results
    results = _parse_browser_results(raw)
    if not results:
        # Fallback: try Gemini Flash to structure the raw output
        results = await _gemini_parse_fallback(raw, language)

    if not results:
        return {
            "action": "error",
            "text": (
                f"I searched <b>{site}</b> but couldn't extract hotel data.\n\n"
                "Raw output:\n"
                f"<code>{_truncate(raw, 500)}</code>\n\n"
                "Try again or search a different platform."
            ),
            "buttons": [
                {"text": "Try again", "callback": f"hotel_login_ready:{flow_id}"},
                {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
            ],
        }

    # Store results
    state["step"] = "awaiting_selection"
    state["results"] = results[:MAX_RESULTS]
    await _set_state(user_id, state)

    # Format and return
    text = _format_results_telegram(results[:MAX_RESULTS], site, parsed)
    buttons = _build_result_buttons(results[:MAX_RESULTS], flow_id)

    return {"action": "results", "text": text, "buttons": buttons}


# ── Selection & Filtering ────────────────────────────────────────────────────


async def handle_hotel_selection(
    user_id: str, index: int
) -> dict[str, Any]:
    """User selected a hotel from results.

    Returns dict with: action, text, buttons.
    """
    state = await get_booking_state(user_id)
    if not state or state.get("step") != "awaiting_selection":
        return {"action": "no_flow", "text": "No active hotel search."}

    results = state.get("results", [])
    if index < 0 or index >= len(results):
        return {
            "action": "error",
            "text": f"Invalid selection. Choose 1-{len(results)}.",
        }

    selected = results[index]
    state["selected_hotel"] = selected
    state["step"] = "confirming"
    await _set_state(user_id, state)

    flow_id = state["flow_id"]
    text = _format_confirmation_telegram(selected, state.get("parsed", {}))

    return {
        "action": "confirm",
        "text": text,
        "buttons": [
            {"text": "Confirm booking", "callback": f"hotel_confirm:{flow_id}"},
            {"text": "Back to results", "callback": f"hotel_back:{flow_id}"},
            {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
        ],
    }


async def handle_text_input(
    user_id: str, text: str
) -> dict[str, Any] | None:
    """Handle free text input during hotel booking flow.

    Routes to selection (number/name), sort commands, or returns None if no match.
    """
    state = await get_booking_state(user_id)
    if not state:
        return None

    step = state.get("step")
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # During awaiting_login: "готово" / "done" / "ready"
    if step == "awaiting_login":
        ready_words = ("готово", "done", "ready", "ok", "сохранил", "saved")
        if any(w in text_lower for w in ready_words):
            return await handle_login_ready(user_id)
        return None

    # During awaiting_selection
    if step == "awaiting_selection":
        results = state.get("results", [])

        # Try matching by number
        if text_stripped.isdigit():
            idx = int(text_stripped) - 1  # 1-based → 0-based
            if 0 <= idx < len(results):
                return await handle_hotel_selection(user_id, idx)

        # Try matching by hotel name (fuzzy substring)
        for i, r in enumerate(results):
            if text_lower in r.get("name", "").lower():
                return await handle_hotel_selection(user_id, i)

        # Sort commands
        sort_patterns = {
            "price": r"(?:по цене|cheapest|price|дешев|цена)",
            "rating": r"(?:по рейтинг|rating|best rated|лучши|рейтинг)",
            "distance": r"(?:по расстояни|distance|closest|ближ|центр)",
        }
        for sort_type, pattern in sort_patterns.items():
            if re.search(pattern, text_lower):
                return await handle_sort_change(user_id, sort_type)

        # Filter by landmark/distance
        distance_match = re.search(
            r"(?:ближе к|near|close to|рядом с)\s+(.+)",
            text_lower,
        )
        if distance_match:
            landmark = distance_match.group(1).strip()
            return await handle_sort_change(
                user_id, "distance", landmark=landmark
            )

        return None

    # During confirming: "да" / "yes" / "подтвердить"
    if step == "confirming":
        confirm_words = ("да", "yes", "подтвердить", "confirm", "бронируй", "book")
        if any(w in text_lower for w in confirm_words):
            return await execute_booking(user_id)
        cancel_words = ("нет", "no", "cancel", "отмена", "назад", "back")
        if any(w in text_lower for w in cancel_words):
            return await handle_back_to_results(user_id)
        return None

    return None


async def handle_sort_change(
    user_id: str,
    sort_type: str,
    landmark: str | None = None,
) -> dict[str, Any]:
    """Re-execute browser search with different sorting/filtering.

    Returns dict with: action, text, buttons.
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active hotel search."}

    site = state["site"]
    parsed = state.get("parsed", {})
    flow_id = state["flow_id"]

    # Build filter change description
    changes = []
    if sort_type == "price":
        changes.append("Sort results by price: lowest first")
    elif sort_type == "rating":
        changes.append("Sort results by guest rating: highest first")
    elif sort_type == "distance":
        if landmark:
            changes.append(f"Sort results by distance from {landmark}: closest first")
        else:
            changes.append("Sort results by distance from city center: closest first")

    prompt = _FILTER_TASK_PROMPT.format(
        site_url=_SUPPORTED_PLATFORMS.get(site, f"https://{site}"),
        city=parsed.get("city", ""),
        changes="\n".join(f"- {c}" for c in changes),
        max_results=MAX_RESULTS,
    )

    state["step"] = "browser_searching"
    await _set_state(user_id, state)

    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=site,
        task=prompt,
        max_steps=FILTER_MAX_STEPS,
        timeout=FILTER_TIMEOUT,
    )

    raw = result.get("result", "")
    results = _parse_browser_results(raw)

    if not results:
        # Sort change failed — keep existing results
        state["step"] = "awaiting_selection"
        await _set_state(user_id, state)
        return {
            "action": "error",
            "text": "Couldn't apply the filter. Here are the previous results.",
            "buttons": _build_result_buttons(
                state.get("results", []), flow_id
            ),
        }

    state["step"] = "awaiting_selection"
    state["results"] = results[:MAX_RESULTS]
    if sort_type:
        parsed["sort_by"] = sort_type
        state["parsed"] = parsed
    await _set_state(user_id, state)

    text = _format_results_telegram(results[:MAX_RESULTS], site, parsed)
    buttons = _build_result_buttons(results[:MAX_RESULTS], flow_id)

    return {"action": "results", "text": text, "buttons": buttons}


async def handle_more_results(user_id: str) -> dict[str, Any]:
    """Fetch more results (next page) via Browser-Use.

    Returns dict with: action, text, buttons.
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active hotel search."}

    site = state["site"]
    parsed = state.get("parsed", {})
    flow_id = state["flow_id"]
    page = state.get("page", 1) + 1

    prompt = (
        f"You are on {_SUPPORTED_PLATFORMS.get(site, f'https://{site}')} "
        f"viewing hotel search results for \"{parsed.get('city', '')}\".\n\n"
        f"Scroll down or go to page {page} to see more results.\n"
        f"Extract the next {MAX_RESULTS} hotels in the same JSON array format."
    )

    state["step"] = "browser_searching"
    await _set_state(user_id, state)

    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=site,
        task=prompt,
        max_steps=FILTER_MAX_STEPS,
        timeout=FILTER_TIMEOUT,
    )

    raw = result.get("result", "")
    results = _parse_browser_results(raw)

    if not results:
        state["step"] = "awaiting_selection"
        await _set_state(user_id, state)
        return {
            "action": "error",
            "text": "No more results found. Here are the current options.",
            "buttons": _build_result_buttons(
                state.get("results", []), flow_id
            ),
        }

    state["step"] = "awaiting_selection"
    state["results"] = results[:MAX_RESULTS]
    state["page"] = page
    await _set_state(user_id, state)

    text = _format_results_telegram(results[:MAX_RESULTS], site, parsed)
    buttons = _build_result_buttons(results[:MAX_RESULTS], flow_id)

    return {"action": "results", "text": text, "buttons": buttons}


async def handle_back_to_results(user_id: str) -> dict[str, Any]:
    """Go back to results from confirmation screen."""
    state = await get_booking_state(user_id)
    if not state:
        return {"action": "no_flow", "text": "No active hotel search."}

    state["step"] = "awaiting_selection"
    state["selected_hotel"] = None
    await _set_state(user_id, state)

    results = state.get("results", [])
    flow_id = state["flow_id"]
    site = state.get("site", "")
    parsed = state.get("parsed", {})

    if not results:
        return {"action": "no_results", "text": "No results to show."}

    text = _format_results_telegram(results, site, parsed)
    buttons = _build_result_buttons(results, flow_id)
    return {"action": "results", "text": text, "buttons": buttons}


# ── Booking Execution ────────────────────────────────────────────────────────


async def execute_booking(user_id: str) -> dict[str, Any]:
    """Navigate to booking form via Browser-Use. Stops before payment.

    Returns dict with: action, text, buttons.
    Actions: "ready", "payment_required", "sold_out", "price_changed",
             "login_required", "error"
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state or state.get("step") not in ("confirming", "awaiting_login"):
        return {"action": "error", "text": "No booking to confirm."}

    hotel = state.get("selected_hotel")
    if not hotel:
        return {"action": "error", "text": "No hotel selected."}

    site = state["site"]
    parsed = state.get("parsed", {})
    flow_id = state["flow_id"]

    # Check session
    storage_state = await browser_service.get_storage_state(user_id, site)
    if not storage_state:
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await check_auth_and_search(user_id)

    state["step"] = "browser_booking"
    await _set_state(user_id, state)

    prompt = _BOOKING_TASK_PROMPT.format(
        site_url=_SUPPORTED_PLATFORMS.get(site, f"https://{site}"),
        hotel_name=hotel.get("name", ""),
        check_in=parsed.get("check_in", ""),
        check_out=parsed.get("check_out", ""),
        guests=parsed.get("guests", 2),
        room_type=hotel.get("room_type", "cheapest available"),
    )

    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=site,
        task=prompt,
        max_steps=BOOKING_MAX_STEPS,
        timeout=BOOKING_TIMEOUT,
    )

    raw = result.get("result", "")
    booking_data = _extract_json_object(raw)

    if not booking_data:
        # Try to detect status from raw text
        status = _detect_booking_status(raw)
        booking_data = {"status": status, "raw": raw}

    status = booking_data.get("status", "").upper()

    if status == "SOLD_OUT":
        state["step"] = "awaiting_selection"
        state["selected_hotel"] = None
        await _set_state(user_id, state)
        return {
            "action": "sold_out",
            "text": (
                f"<b>{hotel.get('name', 'This hotel')}</b> is no longer "
                "available at this price.\n\n"
                "Select a different hotel from the results."
            ),
            "buttons": _build_result_buttons(
                state.get("results", []), flow_id
            ),
        }

    if status == "LOGIN_REQUIRED":
        state["step"] = "awaiting_login"
        await _set_state(user_id, state)
        return await check_auth_and_search(user_id)

    if status == "PAYMENT_REQUIRED":
        booking_url = booking_data.get("booking_url", "")
        final_price = booking_data.get("final_price", hotel.get("total_price", ""))
        cancellation = booking_data.get(
            "cancellation_policy", hotel.get("cancellation", "")
        )

        state["step"] = "payment_handoff"
        state["booking_data"] = booking_data
        await _set_state(user_id, state)

        text = (
            f"<b>Payment required</b>\n\n"
            f"Hotel: <b>{hotel.get('name', '')}</b>\n"
            f"Total: <b>{final_price}</b>\n"
        )
        if cancellation:
            text += f"Cancellation: {cancellation}\n"
        text += (
            "\nThe booking is ready but requires payment. "
            "Please complete the payment using the link below."
        )

        buttons = []
        if booking_url:
            buttons.append({"text": "Complete payment", "url": booking_url})
        buttons.append({"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"})

        return {"action": "payment_required", "text": text, "buttons": buttons}

    if status == "READY_TO_BOOK":
        # Check if price changed
        expected = hotel.get("total_price", "")
        actual = booking_data.get("final_price", "")
        if expected and actual and expected != actual:
            state["booking_data"] = booking_data
            await _set_state(user_id, state)
            return {
                "action": "price_changed",
                "text": (
                    f"<b>Price changed</b>\n\n"
                    f"Expected: {expected}\n"
                    f"Actual: <b>{actual}</b>\n\n"
                    "Proceed at the new price?"
                ),
                "buttons": [
                    {"text": "Proceed", "callback": f"hotel_confirm_final:{flow_id}"},
                    {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"},
                ],
            }

        # Ready — confirm immediately
        return await confirm_booking(user_id)

    # Unknown status — try to proceed
    await _clear_state(user_id)
    return {
        "action": "error",
        "text": (
            f"Booking result unclear.\n\n"
            f"<code>{_truncate(raw, 800)}</code>"
        ),
    }


async def confirm_booking(user_id: str) -> dict[str, Any]:
    """Click the final booking button (no-payment flow).

    Returns dict with: action, text.
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state:
        return {"action": "error", "text": "No booking to confirm."}

    hotel = state.get("selected_hotel", {})
    site = state.get("site", "")

    prompt = _CONFIRM_BOOKING_PROMPT.format(
        site_url=_SUPPORTED_PLATFORMS.get(site, f"https://{site}"),
    )

    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=state["family_id"],
        site=site,
        task=prompt,
        max_steps=10,
        timeout=60,
    )

    raw = result.get("result", "")
    confirmation = _extract_json_object(raw)

    await _clear_state(user_id)

    if confirmation and confirmation.get("confirmation_number"):
        return {
            "action": "success",
            "text": _format_booking_success(confirmation, hotel),
        }

    # Even without structured confirmation, booking may have succeeded
    if result.get("success"):
        return {
            "action": "success",
            "text": (
                f"<b>Booking submitted!</b>\n\n"
                f"Hotel: {hotel.get('name', 'N/A')}\n\n"
                f"{_truncate(raw, 500)}\n\n"
                "Check your email for confirmation details."
            ),
        }

    return {
        "action": "error",
        "text": f"Booking may not have completed:\n\n{_truncate(raw, 500)}",
    }


async def cancel_flow(user_id: str) -> None:
    """Cancel the active hotel booking flow."""
    await _clear_state(user_id)


# ── Prompt Builders ──────────────────────────────────────────────────────────


def _build_search_prompt(site: str, parsed: dict) -> str:
    """Build the Browser-Use search task prompt."""
    site_url = _SUPPORTED_PLATFORMS.get(site, f"https://{site}")
    filter_section = ""
    filter_steps = ""

    if parsed.get("budget_per_night"):
        filter_section += f"MAX PRICE: ${parsed['budget_per_night']} per night\n"
        filter_steps += (
            "- Apply a price filter if available "
            f"(max ${parsed['budget_per_night']}/night)\n"
        )

    if parsed.get("star_rating"):
        filter_section += f"MINIMUM STARS: {parsed['star_rating']}\n"
        filter_steps += f"- Filter by {parsed['star_rating']}+ stars if available\n"

    if parsed.get("amenities"):
        amenities_str = ", ".join(parsed["amenities"])
        filter_section += f"AMENITIES: {amenities_str}\n"
        filter_steps += f"- Filter by amenities: {amenities_str}\n"

    if parsed.get("distance_from"):
        filter_section += f"NEAR: {parsed['distance_from']}\n"
        filter_steps += (
            f"- Sort by distance from {parsed['distance_from']} if possible\n"
        )

    sort_map = {
        "price": "- Sort results by price: lowest first\n",
        "rating": "- Sort results by guest rating: highest first\n",
        "distance": "- Sort results by distance from center: closest first\n",
    }
    sort_by = parsed.get("sort_by", "best_value")
    if sort_by in sort_map:
        filter_steps += sort_map[sort_by]

    return _SEARCH_TASK_PROMPT.format(
        site_url=site_url,
        city=parsed.get("city", ""),
        check_in=parsed.get("check_in", ""),
        check_out=parsed.get("check_out", ""),
        guests=parsed.get("guests", 2),
        filter_section=filter_section or "No specific filters.\n",
        filter_steps=filter_steps or "",
        max_results=MAX_RESULTS,
    )


def _build_direct_search_url(site: str, parsed: dict) -> str:
    """Build a direct URL for manual search (CAPTCHA fallback)."""
    city = parsed.get("city", "").replace(" ", "+")
    if site == "booking.com":
        return f"https://www.booking.com/searchresults.html?ss={city}"
    if site == "airbnb.com":
        return f"https://www.airbnb.com/s/{city}/homes"
    return _SUPPORTED_PLATFORMS.get(site, f"https://{site}")


# ── Result Parsing ───────────────────────────────────────────────────────────


def _parse_browser_results(raw_text: str) -> list[dict[str, Any]]:
    """Parse Browser-Use output into structured hotel results.

    Tries JSON parsing first, then regex fallback.
    """
    if not raw_text:
        return []

    # Try direct JSON parse
    results = _extract_json_array(raw_text)
    if results:
        return _validate_results(results)

    # Try extracting JSON from within text
    json_match = re.search(r"\[[\s\S]*\]", raw_text)
    if json_match:
        try:
            results = json.loads(json_match.group())
            if isinstance(results, list):
                return _validate_results(results)
        except (json.JSONDecodeError, ValueError):
            pass

    return []


async def _gemini_parse_fallback(
    raw_text: str, language: str
) -> list[dict[str, Any]]:
    """Use Gemini Flash to parse unstructured browser output into hotel JSON."""
    from src.core.llm.clients import generate_text

    if not raw_text or len(raw_text) < 20:
        return []

    try:
        prompt = (
            "Extract hotel information from this text and return a JSON array.\n\n"
            "Text:\n"
            f"{raw_text[:3000]}\n\n"
            "Return ONLY a JSON array of objects with these fields:\n"
            "name, price_per_night, total_price, rating, review_count, "
            "distance, amenities (array), cancellation, description"
        )
        result = await generate_text(
            "gemini-3-flash-preview",
            "You extract structured hotel data from text. Return only valid JSON.",
            max_tokens=1024,
            prompt=prompt,
        )
        parsed = _extract_json_array(result)
        return _validate_results(parsed) if parsed else []
    except Exception as e:
        logger.warning("Gemini parse fallback failed: %s", e)
        return []


def _validate_results(results: list) -> list[dict[str, Any]]:
    """Validate and normalize hotel result objects."""
    valid = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if not r.get("name"):
            continue
        # Normalize fields
        hotel = {
            "name": str(r.get("name", "")),
            "price_per_night": str(r.get("price_per_night", "")),
            "total_price": str(r.get("total_price", "")),
            "rating": str(r.get("rating", "")),
            "review_count": str(r.get("review_count", "")),
            "distance": str(r.get("distance", "")),
            "amenities": r.get("amenities", []),
            "cancellation": str(r.get("cancellation", "")),
            "description": str(r.get("description", "")),
        }
        if not isinstance(hotel["amenities"], list):
            hotel["amenities"] = []
        valid.append(hotel)
    return valid


# ── Telegram Formatting ──────────────────────────────────────────────────────


def _format_preview_telegram(raw: str, city: str) -> str:
    """Format Gemini Grounding price preview for Telegram."""
    if not raw:
        return "<i>Price preview unavailable</i>"
    # Clean up and truncate
    text = raw.strip()[:1500]
    # Convert markdown bold to HTML
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text


def _format_results_telegram(
    results: list[dict], site: str, parsed: dict
) -> str:
    """Format hotel search results as Telegram HTML."""
    if not results:
        return f"No hotels found on <b>{site}</b>."

    sort_label = {
        "best_value": "Best value",
        "price": "Price (low to high)",
        "rating": "Rating (high to low)",
        "distance": "Distance (closest)",
    }.get(parsed.get("sort_by", "best_value"), "Best value")

    lines = [
        f"<b>Hotels on {site}</b>",
        f"Sorted by: {sort_label} | {len(results)} results\n",
    ]

    for i, r in enumerate(results):
        name = r.get("name", "Unknown")
        price = r.get("price_per_night", "")
        total = r.get("total_price", "")
        rating = r.get("rating", "")
        reviews = r.get("review_count", "")
        distance = r.get("distance", "")
        amenities = r.get("amenities", [])
        cancellation = r.get("cancellation", "")

        line = f"<b>{i + 1}.</b> {name}\n"
        price_parts = []
        if price:
            price_parts.append(price)
        if total:
            price_parts.append(f"({total} total)")
        if price_parts:
            line += f"   {' '.join(price_parts)}"
        if rating:
            line += f" | {rating}/10"
            if reviews:
                line += f" ({reviews} reviews)"
        line += "\n"
        if distance:
            line += f"   {distance}"
            if amenities:
                line += f" | {', '.join(amenities[:4])}"
            line += "\n"
        elif amenities:
            line += f"   {', '.join(amenities[:4])}\n"
        if cancellation:
            line += f"   <i>{cancellation}</i>\n"

        lines.append(line)

    lines.append("<i>Select a hotel or adjust your search:</i>")
    return "\n".join(lines)


def _format_confirmation_telegram(hotel: dict, parsed: dict) -> str:
    """Format booking confirmation message."""
    name = hotel.get("name", "")
    price = hotel.get("price_per_night", "")
    total = hotel.get("total_price", "")
    rating = hotel.get("rating", "")
    cancellation = hotel.get("cancellation", "")

    nights = _calc_nights(parsed.get("check_in"), parsed.get("check_out"))
    dates = _format_dates(parsed.get("check_in"), parsed.get("check_out"))

    text = "<b>Confirm booking:</b>\n\n"
    text += f"Hotel: <b>{name}</b>\n"
    if rating:
        text += f"Rating: {rating}/10\n"
    text += f"Dates: {dates} ({nights} {'night' if nights == 1 else 'nights'})\n"
    if price:
        text += f"Price: <b>{price}</b>"
        if total:
            text += f" (<b>{total}</b> total)"
        text += "\n"
    if cancellation:
        text += f"Cancellation: <i>{cancellation}</i>\n"

    text += "\nProceed with booking?"
    return text


def _format_booking_success(confirmation: dict, hotel: dict) -> str:
    """Format successful booking message."""
    conf_num = confirmation.get("confirmation_number", "N/A")
    name = confirmation.get("hotel_name", hotel.get("name", ""))
    check_in = confirmation.get("check_in", "")
    check_out = confirmation.get("check_out", "")
    total = confirmation.get("total_price", hotel.get("total_price", ""))
    cancellation = confirmation.get("cancellation_policy", "")
    instructions = confirmation.get("special_instructions", "")

    text = "<b>Booking confirmed!</b>\n\n"
    text += f"Confirmation: <b>{conf_num}</b>\n"
    text += f"Hotel: <b>{name}</b>\n"
    if check_in:
        text += f"Check-in: {check_in}\n"
    if check_out:
        text += f"Check-out: {check_out}\n"
    if total:
        text += f"Total: <b>{total}</b>\n"
    if cancellation:
        text += f"\nCancellation: {cancellation}\n"
    if instructions:
        text += f"\n<i>{instructions}</i>\n"
    text += "\nCheck your email for full details."
    return text


def _build_result_buttons(
    results: list[dict], flow_id: str
) -> list[dict[str, str]]:
    """Build inline buttons for hotel search results."""
    buttons = []
    for i, r in enumerate(results):
        name = r.get("name", f"Hotel {i + 1}")
        price = r.get("price_per_night", "")
        label = f"{i + 1}. {name}"
        if price:
            label += f" — {price}"
        if len(label) > 50:
            label = label[:47] + "..."
        buttons.append({
            "text": label,
            "callback": f"hotel_select:{flow_id}:{i}",
        })

    # Sort buttons
    buttons.append({
        "text": "Sort: price | rating | distance",
        "callback": f"hotel_sort:{flow_id}:price",
    })
    buttons.append({
        "text": "More results",
        "callback": f"hotel_more:{flow_id}",
    })
    buttons.append({
        "text": "Cancel",
        "callback": f"hotel_cancel:{flow_id}",
    })
    return buttons


# ── Utility Helpers ──────────────────────────────────────────────────────────


def _extract_json_object(text: str) -> dict | None:
    """Try to extract a JSON object from text."""
    if not text:
        return None
    # Try direct parse
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
    # Try finding JSON in text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _extract_json_array(text: str) -> list | None:
    """Try to extract a JSON array from text."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("["):
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else None
        except (json.JSONDecodeError, ValueError):
            pass
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            result = json.loads(match.group())
            return result if isinstance(result, list) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _detect_booking_status(raw: str) -> str:
    """Detect booking status from raw Browser-Use output."""
    raw_upper = raw.upper()
    if "SOLD_OUT" in raw_upper or "SOLD OUT" in raw_upper or "NOT AVAILABLE" in raw_upper:
        return "SOLD_OUT"
    if "LOGIN" in raw_upper or "SIGN IN" in raw_upper:
        return "LOGIN_REQUIRED"
    if "PAYMENT" in raw_upper or "CREDIT CARD" in raw_upper or "PAY NOW" in raw_upper:
        return "PAYMENT_REQUIRED"
    if "CAPTCHA" in raw_upper:
        return "CAPTCHA_DETECTED"
    if "CONFIRM" in raw_upper or "BOOKED" in raw_upper or "RESERV" in raw_upper:
        return "READY_TO_BOOK"
    return "UNKNOWN"


def _calc_nights(check_in: str | None, check_out: str | None) -> int:
    """Calculate number of nights between dates."""
    if not check_in or not check_out:
        return 1
    try:
        from datetime import date

        d_in = date.fromisoformat(check_in)
        d_out = date.fromisoformat(check_out)
        return max((d_out - d_in).days, 1)
    except (ValueError, TypeError):
        return 1


def _format_dates(check_in: str | None, check_out: str | None) -> str:
    """Format date range for display."""
    if not check_in or not check_out:
        return "dates TBD"
    try:
        from datetime import date

        d_in = date.fromisoformat(check_in)
        d_out = date.fromisoformat(check_out)
        return f"{d_in.strftime('%b %d')} — {d_out.strftime('%b %d, %Y')}"
    except (ValueError, TypeError):
        return f"{check_in} — {check_out}"


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
