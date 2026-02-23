"""Multi-step hotel booking flow via Telegram.

Conversational flow using Redis state (same pattern as browser_login):
1. Search hotels via Gemini Google Search Grounding (fast, 2-3s)
2. Show results with inline selection buttons
3. User picks a hotel → confirmation with price
4. Browser-Use with saved cookies books the selected hotel

States: searching → awaiting_selection → confirming → done
Redis key: browser_booking:{user_id} (TTL 600s)
"""

import json
import logging
import re
import uuid
from typing import Any

from src.core.db import redis

logger = logging.getLogger(__name__)

BOOKING_FLOW_TTL = 600  # 10 minutes
_REDIS_PREFIX = "browser_booking"

_SEARCH_PROMPT = """\
Find top 5 hotels for this request: {task}
Site preference: {site}

For each hotel return EXACTLY this format (one per line):
[N] Hotel Name | $Price/night | Rating/10 | Short location/feature

Example:
[1] Hotel Arts Barcelona | $135/night | 8.9 | Beachfront, Olympic Port
[2] W Barcelona | $180/night | 8.7 | Iconic sail-shaped building

Rules:
- Maximum 5 results, sorted by best value
- Real hotels with real current prices from search results
- Include rating (out of 10) if available, otherwise skip the rating field
- Price MUST be per night in USD
- Respond in {language}"""


async def get_booking_state(user_id: str) -> dict | None:
    """Get the current booking flow state from Redis."""
    raw = await redis.get(f"{_REDIS_PREFIX}:{user_id}")
    if not raw:
        return None
    return json.loads(raw)


async def _set_booking_state(user_id: str, state: dict) -> None:
    """Store booking flow state in Redis."""
    await redis.set(
        f"{_REDIS_PREFIX}:{user_id}",
        json.dumps(state, ensure_ascii=False),
        ex=BOOKING_FLOW_TTL,
    )


async def _clear_booking_state(user_id: str) -> None:
    """Clear booking flow state from Redis."""
    await redis.delete(f"{_REDIS_PREFIX}:{user_id}")


def _parse_results(raw_text: str) -> list[dict[str, str]]:
    """Parse structured hotel results from Gemini Grounding response.

    Expected format per line:
        [N] Hotel Name | $Price/night | Rating | Description

    Returns list of dicts: [{name, price, rating, description}, ...]
    """
    results = []
    pattern = re.compile(
        r"\[(\d+)\]\s*(.+?)\s*\|\s*(\$[\d,.]+/night)\s*\|\s*([\d.]+)\s*\|\s*(.+)"
    )
    for line in raw_text.strip().splitlines():
        m = pattern.match(line.strip())
        if m:
            results.append({
                "name": m.group(2).strip(),
                "price": m.group(3).strip(),
                "rating": m.group(4).strip(),
                "description": m.group(5).strip(),
            })
    return results


def _format_for_telegram(
    results: list[dict[str, str]], site: str, raw_text: str
) -> str:
    """Format search results as Telegram HTML."""
    if not results:
        # Parsing failed — show raw text
        fallback = raw_text[:2000] if raw_text else "No results found."
        return (
            f"<b>Hotels on {site}:</b>\n\n"
            f"{fallback}\n\n"
            "<i>Type the hotel number or name to select it.</i>"
        )

    lines = [f"<b>Hotels on {site}:</b>\n"]
    for i, r in enumerate(results):
        rating_str = f" | {r['rating']}/10" if r.get("rating") else ""
        lines.append(
            f"<b>{i + 1}.</b> {r['name']}\n"
            f"   {r['price']}{rating_str}\n"
            f"   <i>{r['description']}</i>\n"
        )
    lines.append("<i>Select a hotel to book:</i>")
    return "\n".join(lines)


def _format_confirmation(selected: dict[str, str], task: str, site: str) -> str:
    """Format a booking confirmation message."""
    return (
        f"<b>Confirm booking:</b>\n\n"
        f"Hotel: <b>{selected['name']}</b>\n"
        f"Price: {selected['price']}\n"
        f"Site: {site}\n\n"
        f"Task: <i>{task}</i>\n\n"
        "This may involve a payment. Proceed?"
    )


async def start_search(
    user_id: str,
    family_id: str,
    site: str,
    task: str,
    language: str = "en",
) -> dict[str, Any]:
    """Search for hotels via Gemini Grounding and return formatted results.

    Returns dict with: text (HTML), buttons (list of callback buttons).
    """
    from google.genai import types

    from src.core.llm.clients import google_client

    try:
        client = google_client()
        prompt = _SEARCH_PROMPT.format(
            task=task, site=site, language=language,
        )
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        raw_text = response.text or ""
    except Exception as e:
        logger.warning("Gemini booking search failed: %s", e)
        raw_text = ""

    results = _parse_results(raw_text)
    flow_id = str(uuid.uuid4())[:8]

    await _set_booking_state(user_id, {
        "flow_id": flow_id,
        "step": "awaiting_selection",
        "site": site,
        "task": task,
        "family_id": family_id,
        "results": results,
        "raw_text": raw_text[:3000],
    })

    buttons = []
    for i, r in enumerate(results[:5]):
        label = f"{i + 1}. {r['name']}"
        if len(label) > 40:
            label = label[:37] + "..."
        buttons.append({
            "text": label,
            "callback": f"booking_select:{flow_id}:{i}",
        })

    return {
        "text": _format_for_telegram(results, site, raw_text),
        "buttons": buttons if buttons else None,
    }


async def handle_selection(
    user_id: str, option_idx: int
) -> dict[str, Any]:
    """Handle user's hotel selection.

    Returns dict with: action, text, buttons.
    Actions: "confirm", "no_flow", "error"
    """
    state = await get_booking_state(user_id)
    if not state or state.get("step") != "awaiting_selection":
        return {"action": "no_flow", "text": "No active booking search."}

    results = state.get("results", [])
    if option_idx < 0 or option_idx >= len(results):
        return {
            "action": "error",
            "text": f"Invalid selection. Choose 1-{len(results)}.",
        }

    selected = results[option_idx]
    state["selected_idx"] = option_idx
    state["step"] = "confirming"
    await _set_booking_state(user_id, state)

    flow_id = state["flow_id"]
    return {
        "action": "confirm",
        "text": _format_confirmation(selected, state["task"], state["site"]),
        "buttons": [
            {"text": "Confirm", "callback": f"booking_confirm:{flow_id}"},
            {"text": "Cancel", "callback": f"booking_cancel:{flow_id}"},
        ],
    }


async def handle_text_selection(
    user_id: str, text: str
) -> dict[str, Any] | None:
    """Handle text-based selection (user types number or hotel name).

    Returns result dict if matched, None if text doesn't match any option.
    """
    state = await get_booking_state(user_id)
    if not state or state.get("step") != "awaiting_selection":
        return None

    results = state.get("results", [])
    if not results:
        return None

    text = text.strip()

    # Try matching by number (e.g., "2" or "3")
    if text.isdigit():
        idx = int(text) - 1  # 1-based → 0-based
        if 0 <= idx < len(results):
            return await handle_selection(user_id, idx)

    # Try matching by hotel name (fuzzy substring)
    text_lower = text.lower()
    for i, r in enumerate(results):
        if text_lower in r["name"].lower():
            return await handle_selection(user_id, i)

    return None


async def execute_booking(user_id: str) -> dict[str, Any]:
    """Execute the actual booking via Browser-Use with saved cookies.

    Returns dict with: action, text, screenshot_bytes (optional).
    Actions: "success", "need_login", "error"
    """
    from src.tools import browser_service

    state = await get_booking_state(user_id)
    if not state or state.get("step") not in ("confirming", "awaiting_login"):
        return {"action": "error", "text": "No booking to confirm."}

    selected_idx = state.get("selected_idx")
    results = state.get("results", [])
    if selected_idx is None or selected_idx >= len(results):
        await _clear_booking_state(user_id)
        return {"action": "error", "text": "Invalid booking selection."}

    selected = results[selected_idx]
    site = state["site"]
    family_id = state["family_id"]
    task = state["task"]

    # Check for saved browser session
    storage_state = await browser_service.get_storage_state(user_id, site)
    if not storage_state:
        # Store the booking task so we can resume after login
        state["step"] = "awaiting_login"
        await _set_booking_state(user_id, state)
        return {
            "action": "need_login",
            "site": site,
            "family_id": family_id,
            "task": f"Book {selected['name']} — {task}",
        }

    # Execute with Browser-Use
    booking_task = (
        f"Go to {site} and book this hotel: {selected['name']}. "
        f"Original request: {task}. "
        f"Expected price: {selected['price']}. "
        "Navigate to the hotel page, select the dates, and proceed to booking."
    )

    result = await browser_service.execute_with_session(
        user_id=user_id,
        family_id=family_id,
        site=site,
        task=booking_task,
    )

    await _clear_booking_state(user_id)

    if result["success"]:
        return {
            "action": "success",
            "text": (
                f"<b>Booking submitted!</b>\n\n"
                f"Hotel: {selected['name']}\n"
                f"Price: {selected['price']}\n\n"
                f"{result['result']}"
            ),
        }

    return {
        "action": "error",
        "text": f"Booking failed: {result['result']}",
    }


async def cancel_booking(user_id: str) -> None:
    """Cancel an active booking flow."""
    await _clear_booking_state(user_id)
