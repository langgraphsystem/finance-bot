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

import asyncio
import json
import logging
import re
import uuid
from typing import Any
from urllib.parse import quote

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
The message may be in any language (English, Russian, Spanish, etc.) — extract all fields.

Message: "{task}"
Message language: {language}
Today's date: {today}

Return:
{{"city": "city name in English",
  "check_in": "YYYY-MM-DD or null",
  "check_out": "YYYY-MM-DD or null",
  "guests": 2,
  "budget_per_night": null or number,
  "currency": "USD",
  "amenities": [],
  "star_rating": null or number,
  "distance_from": null or "landmark name in English",
  "sort_by": "best_value"}}

Rules:
- ALWAYS translate city names to English (e.g. "Чикаго" → "Chicago", "Москва" → "Moscow")
- If dates are relative ("next week", "завтра"), calculate from today
- If only duration given ("на 3 ночи"), set check_in to tomorrow
- Default guests=2 if not specified
- Keep budget as number only (no currency symbol)
- Extract budget from any format: "150 долларов" → 150, "$200" → 200, "до 100€" → 100
- If info is missing, set to null
- "ближе к центру" / "near center" → distance_from: "city center"
- You MUST return valid JSON even if some fields are null"""

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
1. Close any popups, overlays, or cookie banners
2. Enter the destination "{city}" in the search box and select it from the dropdown
3. Set check-in date to {check_in} and check-out date to {check_out} using the date picker
4. Set {guests} adults, 0 children
5. Click Search
6. Wait for results to fully load (wait for hotel cards to appear)
{filter_steps}
7. Extract hotel data using JavaScript. Run this in the browser console:

{js_extraction}

8. Return the JavaScript output as your final answer (the JSON array).

IMPORTANT:
- Stay on the search results page. Do NOT click on individual hotels.
- Use the JavaScript extraction above — do NOT try to read hotel data from the page visually.
- If the JavaScript returns an empty array, try scrolling down and running it again.
- If a CAPTCHA appears, STOP and return exactly: CAPTCHA_DETECTED
- If the site asks to log in or sign in, STOP and return exactly: LOGIN_REQUIRED
- If no results are found after search, return exactly: NO_RESULTS"""

# ── Site-Specific JS Extraction Scripts ─────────────────────────────────────
# These use data-testid / known CSS selectors for each platform.
# Validated against real sites in browser-use testing (Feb 2026).

_JS_EXTRACT_BOOKING = (
    "JSON.stringify(Array.from("
    "document.querySelectorAll('[data-testid=\"property-card\"]')"
    ").slice(0,{max_results}).map(c=>({{"
    "name:c.querySelector('[data-testid=\"title\"]')"
    "?.textContent?.trim()||"
    "c.querySelector('.sr-hotel__name')?.textContent?.trim()||'',"
    "price_per_night:c.querySelector("
    "'[data-testid=\"price-and-discounted-price\"]')"
    "?.textContent?.trim()||"
    "c.querySelector('.bui-price-display__value')"
    "?.textContent?.trim()||'',"
    "total_price:'',"
    "rating:(c.querySelector('[data-testid=\"review-score\"]')"
    "?.textContent?.match(/\\d+\\.\\d/)||[''])[0],"
    "review_count:(c.querySelector("
    "'[data-testid=\"review-score\"]')"
    "?.textContent?.match(/(\\d[\\d,]+)\\s*review/)"
    "||['',''])[1],"
    "distance:c.querySelector('[data-testid=\"distance\"]')"
    "?.textContent?.trim()||"
    "c.querySelector('.distance-from-search')"
    "?.textContent?.trim()||'',"
    "amenities:[],"
    "cancellation:c.querySelector("
    "'[data-testid=\"cancellation-policy\"]')"
    "?.textContent?.trim()||'',"
    "description:c.querySelector("
    "'[data-testid=\"recommended-units\"]')"
    "?.textContent?.trim()||''"
    "}}))))"
)

_JS_EXTRACT_GENERIC = (
    "JSON.stringify(Array.from(document.querySelectorAll("
    "'[data-testid=\"property-card\"], .hotel-card, "
    ".listing-card, .sr_property_block, "
    "[data-hotelid], .property-card'"
    ")).slice(0,{max_results}).map((c,i)=>{{"
    "const g=(s)=>{{"
    "const e=c.querySelector(s);"
    "return e?e.textContent.trim():''}};"
    "const p=g('[data-testid=\"price-and-discounted-price\"]')"
    "||g('.price')||g('[class*=\"price\"]')||'';"
    "const n=g('[data-testid=\"title\"]')||g('h3')"
    "||g('h2')||g('[class*=\"name\"]')||'Hotel '+(i+1);"
    "const r=g('[data-testid=\"review-score\"]')"
    "||g('[class*=\"rating\"]')"
    "||g('[class*=\"score\"]')||'';"
    "const d=g('[data-testid=\"distance\"]')"
    "||g('[class*=\"distance\"]')||'';"
    "return{{name:n,price_per_night:p,total_price:'',"
    "rating:r,review_count:'',distance:d,"
    "amenities:[],cancellation:'',description:''}}"
    "}}))"
)

_JS_EXTRACT_MAP: dict[str, str] = {
    "booking.com": _JS_EXTRACT_BOOKING,
    # Add more site-specific extractors as they are validated:
    # "airbnb.com": _JS_EXTRACT_AIRBNB,
    # "hotels.com": _JS_EXTRACT_HOTELS,
}

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
            task=task, language=language, today=date.today().isoformat()
        )
        raw = await generate_text(
            "gemini-3.1-flash-lite-preview",
            (
                "You extract structured data from multilingual text. "
                "The user message may be in any language. "
                "Return ONLY valid JSON, no extra text or markdown."
            ),
            max_tokens=512,
            prompt=prompt,
        )
        logger.debug("Booking parse raw response: %s", raw)
        parsed = _extract_json_object(raw)
        if not parsed:
            logger.warning(
                "Booking parse: failed to extract JSON from response: %.200s", raw
            )
            return None

        # Validate minimum fields
        if not parsed.get("city"):
            logger.warning("Booking parse: city is empty, parsed=%s", parsed)
            return None

        # Defaults
        parsed.setdefault("guests", 2)
        parsed.setdefault("currency", "USD")
        parsed.setdefault("amenities", [])
        parsed.setdefault("sort_by", "best_value")

        logger.info("Booking parse OK: city=%s, dates=%s-%s", parsed.get("city"),
                     parsed.get("check_in"), parsed.get("check_out"))
        return parsed
    except Exception as e:
        logger.warning("Failed to parse booking request: %s", e, exc_info=True)
        return None


# ── Flow Entry Point ─────────────────────────────────────────────────────────


async def start_flow(
    user_id: str,
    family_id: str,
    task: str,
    language: str = "en",
    pre_parsed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start the hotel booking flow.

    1. Parse request with Gemini Flash (or use pre_parsed from intent detection)
    2. Quick Gemini Grounding price preview
    3. Return platform selection buttons

    Returns dict with: text, buttons, parsed (or error).
    """
    # Use pre-parsed data from intent detection if available, else parse with LLM
    parsed = None
    if pre_parsed and pre_parsed.get("city"):
        parsed = pre_parsed
        parsed.setdefault("guests", 2)
        parsed.setdefault("currency", "USD")
        parsed.setdefault("amenities", [])
        parsed.setdefault("sort_by", "best_value")
        logger.info(
            "Booking using pre-parsed data: city=%s, dates=%s-%s",
            parsed.get("city"), parsed.get("check_in"), parsed.get("check_out"),
        )
    else:
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
            model="gemini-3.1-flash-lite-preview",
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


# ── Playwright-based Search ──────────────────────────────────────────────────

_PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

_BOOKING_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('[data-testid="property-card"]');
    return Array.from(cards).slice(0, %d).map(c => {
        const getText = (sel) => {
            const el = c.querySelector(sel);
            return el ? el.textContent.trim() : '';
        };
        const getLink = () => {
            const a = c.querySelector(
                'a[data-testid="title-link"], a[href*="/hotel/"]'
            );
            return a ? a.href : '';
        };
        const text = c.innerText || '';
        return {
            name: getText('[data-testid="title"]') || getText('h3') || '',
            price_per_night: getText(
                '[data-testid="price-and-discounted-price"]'
            ) || '',
            rating_raw: getText('[data-testid="review-score"]') || '',
            distance: getText('[data-testid="distance"]') || '',
            room_type: getText('[data-testid="recommended-units"]') || '',
            cancellation: (
                text.match(/free cancellation|no prepayment/i) || ['']
            )[0],
            url: getLink(),
        };
    });
}
"""

_HOTEL_DETAILS_JS = """
() => {
    const getText = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.textContent.trim() : '';
    };
    const getAll = (sel) =>
        Array.from(document.querySelectorAll(sel))
            .map(e => e.textContent.trim())
            .filter(t => t.length > 0);
    const rooms = Array.from(
        document.querySelectorAll(
            'tr.js-rt-block-row, [data-testid="room-type"]'
        )
    ).slice(0, 5).map(r => ({
        type: (r.querySelector(
            '.hprt-roomtype-icon-link, [data-testid="room-name"]'
        ) || {}).textContent?.trim() || '',
        price: (r.querySelector(
            '.bui-price-display__value, [data-testid="room-price"]'
        ) || {}).textContent?.trim() || '',
    })).filter(r => r.type);
    const facilities = getAll(
        '[data-testid="facility-group-icon"] + span, '
        + '.hp_desc_important_facilities span, '
        + '[data-testid="property-most-popular-facilities-wrapper"] span'
    ).slice(0, 15);
    const desc = getText(
        '[data-testid="property-description"], '
        + '#property_description_content p'
    );
    const address = getText(
        '[data-testid="PropertyHeaderAddressDesktop-text"], '
        + '#showMap2 .hp_address_subtitle'
    );
    return { rooms, facilities, description: desc?.substring(0, 500) || '',
             address, page_url: window.location.href };
}
"""


def _build_booking_search_url(parsed: dict) -> str:
    """Build booking.com search URL with all parameters."""
    city = parsed.get("city", "")
    params = [
        f"ss={quote(city)}",
        f"checkin={parsed.get('check_in', '')}",
        f"checkout={parsed.get('check_out', '')}",
        f"group_adults={parsed.get('guests', 2)}",
        f"no_rooms={parsed.get('rooms', 1)}",
        f"group_children={parsed.get('children', 0)}",
    ]
    for age in parsed.get("child_ages", []):
        params.append(f"age={age}")

    sort_map = {
        "price": "price",
        "rating": "bayesian_review_score",
        "distance": "distance",
    }
    sort_by = parsed.get("sort_by")
    if sort_by and sort_by in sort_map:
        params.append(f"order={sort_map[sort_by]}")

    nflt_parts = []
    if parsed.get("free_cancel"):
        nflt_parts.append("fc=2")
    if parsed.get("budget_per_night"):
        budget = parsed["budget_per_night"]
        currency = parsed.get("currency", "USD")
        nflt_parts.append(f"price={currency}-min-{budget}-1")
    if nflt_parts:
        params.append(f"nflt={'%3B'.join(nflt_parts)}")

    return f"https://www.booking.com/searchresults.html?{'&'.join(params)}"


async def _execute_playwright_search(
    storage_state: dict,
    parsed: dict,
    site: str,
    fetch_details: bool = False,
) -> list[dict[str, Any]]:
    """Search hotels via Playwright using URL-based navigation + JS extraction.

    Returns list of hotel dicts (empty on failure).
    """
    from playwright.async_api import async_playwright

    if site != "booking.com":
        return []  # Only booking.com supported via Playwright for now

    search_url = _build_booking_search_url(parsed)
    hotels: list[dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            context = await browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 900},
                user_agent=_PLAYWRIGHT_UA,
            )
            page = await context.new_page()

            # Navigate directly to search results
            await page.goto(search_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Close popups
            for sel in [
                '[aria-label="Dismiss sign-in info."]',
                '[id="onetrust-accept-btn-handler"]',
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await page.wait_for_timeout(500)
                except Exception:
                    pass

            # Wait for property cards
            try:
                await page.wait_for_selector(
                    '[data-testid="property-card"]', timeout=15000,
                )
            except Exception:
                await page.wait_for_timeout(5000)

            # Extract hotel data
            raw_hotels = await page.evaluate(
                _BOOKING_EXTRACT_JS % MAX_RESULTS
            )

            if raw_hotels:
                for h in raw_hotels:
                    if not h.get("name"):
                        continue
                    rating = ""
                    review_count = ""
                    rating_raw = h.get("rating_raw", "")
                    if rating_raw:
                        m = re.search(r"(\d+\.?\d*)", rating_raw)
                        if m:
                            rating = m.group(1)
                        m2 = re.search(r"([\d,]+)\s*review", rating_raw)
                        if m2:
                            review_count = m2.group(1)

                    hotels.append({
                        "name": h["name"],
                        "price_per_night": h.get("price_per_night", ""),
                        "total_price": "",
                        "rating": rating,
                        "review_count": review_count,
                        "distance": h.get("distance", ""),
                        "amenities": [],
                        "cancellation": h.get("cancellation", ""),
                        "description": h.get("room_type", ""),
                        "url": h.get("url", ""),
                    })

            # Fetch detailed info for each hotel
            if fetch_details and hotels:
                for i, hotel in enumerate(hotels):
                    url = hotel.get("url")
                    if not url:
                        continue
                    try:
                        details = await _get_hotel_details_pw(context, url)
                        hotels[i].update(details)
                    except Exception as e:
                        logger.warning("Failed to get details for %s: %s",
                                       hotel.get("name"), e)

            await browser.close()

    except Exception as e:
        logger.exception("Playwright search failed: %s", e)

    return hotels


async def _get_hotel_details_pw(context: Any, url: str) -> dict:
    """Open a hotel page in a new tab, extract rooms/facilities/address."""
    details: dict[str, Any] = {}
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        result = await page.evaluate(_HOTEL_DETAILS_JS)
        if result:
            details = {
                "rooms": result.get("rooms", []),
                "facilities": result.get("facilities", []),
                "hotel_description": result.get("description", ""),
                "address": result.get("address", ""),
            }
    except Exception as e:
        details["error"] = str(e)[:200]
    finally:
        await page.close()
    return details


# ── Playwright Booking (navigate → select room → detect payment) ─────────────

_PAYMENT_DETECT_JS = r"""
() => {
    const text = document.body.innerText || '';
    const isPaymentStep = (
        /credit card|debit card|payment (method|detail|info)|card number/i.test(text)
        || /how.*(?:you like to|want to).*pay/i.test(text)
        || !!document.querySelector(
            'input[name*="cc_number"], input[name*="card_number"], '
            + 'input[autocomplete="cc-number"], '
            + '[data-testid="payment-method"], .payment-method, #payment'
        )
    );
    const savedCardMatch = text.match(
        /(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,30}?(\d{4})/i
    );
    let savedCard = savedCardMatch
        ? `${savedCardMatch[1]} ••••${savedCardMatch[2]}`
        : '';
    if (!savedCard) {
        document.querySelectorAll('span, div, label, p').forEach(el => {
            const ct = el.textContent || '';
            if (ct.length < 80 && !savedCard) {
                const m = ct.match(/(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,20}?(\d{4})/i);
                if (m) savedCard = `${m[1]} ••••${m[2]}`;
            }
        });
    }
    const needsCvv = !!document.querySelector(
        'input[name*="cvc"], input[name*="cvv"], '
        + 'input[autocomplete="cc-csc"]'
    );
    const priceEl = document.querySelector(
        '[data-testid="total-price"], .bui-price-display__value, '
        + '.bp-price-details__total-amount, .priceIsland__total-price'
    );
    return {
        is_payment_step: isPaymentStep,
        saved_card: savedCard,
        needs_cvv: needsCvv,
        total_price: priceEl ? priceEl.textContent.trim() : '',
        page_url: window.location.href,
    };
}
"""

_IFRAME_CARD_DETECT_JS = r"""
() => {
    const text = document.body.innerText || '';
    const m = text.match(/(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,30}?(\d{4})/i);
    let card = m ? `${m[1]} ••••${m[2]}` : '';
    if (!card) {
        document.querySelectorAll('span, div, label, p').forEach(el => {
            const ct = el.textContent || '';
            if (ct.length < 80 && !card) {
                const mm = ct.match(/(Visa|Mastercard|Amex|Maestro|JCB)[^\d]{0,20}?(\d{4})/i);
                if (mm) card = `${mm[1]} ••••${mm[2]}`;
            }
        });
    }
    const hasSaved = /saved card|your card|stored card/i.test(text);
    const hasCvv = !!document.querySelector(
        'input[name*="cvc"], input[name*="cvv"], input[autocomplete="cc-csc"]'
    );
    return { saved_card: card, has_saved_card_text: hasSaved, needs_cvv: hasCvv };
}
"""


async def _execute_playwright_booking(
    storage_state: dict,
    hotel: dict,
    parsed: dict,
) -> dict[str, Any]:
    """Navigate to hotel → select room → advance to payment → detect saved card.

    Returns: {status, saved_card, needs_cvv, booking_url, total_price,
              prefilled_name, prefilled_email}
    """
    result: dict[str, Any] = {"status": "ERROR"}

    try:
        from playwright.async_api import async_playwright as _ap
    except ImportError:
        return result

    async with _ap() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        try:
            context = await browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 900},
                user_agent=_PLAYWRIGHT_UA,
            )
            page = await context.new_page()

            hotel_url = hotel.get("url", "")
            if not hotel_url:
                result["status"] = "NO_URL"
                return result

            # Navigate to hotel page
            await page.goto(hotel_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Close popups
            for sel in [
                '[aria-label="Dismiss sign-in info."]',
                '[id="onetrust-accept-btn-handler"]',
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                except Exception:
                    pass

            # Select room from dropdown
            room_selects = page.locator("select.hprt-nos-select")
            if await room_selects.count() > 0:
                first_select = room_selects.first
                await first_select.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
                await first_select.select_option("1")
                await page.wait_for_timeout(1000)

            # Click "I'll reserve"
            reserve_btn = page.locator(
                'button.js-reservation-button, '
                "button:has-text(\"I'll reserve\"), "
                'button:has-text("Reserve")'
            ).first

            if await reserve_btn.is_visible(timeout=5000):
                try:
                    async with page.expect_navigation(
                        wait_until="domcontentloaded", timeout=15000
                    ):
                        await reserve_btn.click()
                except Exception:
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=10000
                        )
                    except Exception:
                        pass
                    await page.wait_for_timeout(3000)

            # Wait for booking page to load
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)

            # Check if we're on the booking form
            url = page.url
            if "book" not in url.lower() and "secure" not in url.lower():
                result["status"] = "NOT_ON_BOOKING_PAGE"
                result["page_url"] = url
                return result

            # Check pre-filled form data
            form_check = await page.evaluate("""
            () => {
                const fn = document.querySelector(
                    'input[name="firstname"], input[name="booker.firstname"]'
                );
                const ln = document.querySelector(
                    'input[name="lastname"], input[name="booker.lastname"]'
                );
                const em = document.querySelector(
                    'input[name="email"], input[name="booker.email"]'
                );
                return {
                    first: fn ? fn.value : '',
                    last: ln ? ln.value : '',
                    email: em ? em.value : '',
                };
            }
            """)
            result["prefilled_name"] = (
                f"{form_check.get('first', '')} {form_check.get('last', '')}".strip()
            )
            result["prefilled_email"] = form_check.get("email", "")

            # Click through booking form steps
            for _step in range(4):
                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await page.wait_for_timeout(1000)

                btn = page.locator(
                    'button:has-text("Next: Final details"), '
                    'button:has-text("Final details"), '
                    'button:has-text("Complete booking"), '
                    'button:has-text("Book now")'
                ).first

                if not await btn.is_visible(timeout=5000):
                    break

                btn_text = (await btn.text_content()).strip()
                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)

                is_complete = any(
                    w in btn_text.lower()
                    for w in ("complete", "finish", "book now")
                )

                try:
                    async with page.expect_navigation(
                        wait_until="domcontentloaded", timeout=15000
                    ):
                        await btn.click()
                except Exception:
                    await page.wait_for_timeout(3000)

                await page.wait_for_timeout(2000)

                if is_complete:
                    # Check for saved card in payment iframe
                    payment = await page.evaluate(_PAYMENT_DETECT_JS)
                    if payment.get("is_payment_step"):
                        break

            # Detect payment + saved card (main page)
            payment = await page.evaluate(_PAYMENT_DETECT_JS)
            result["booking_url"] = page.url
            result["total_price"] = payment.get("total_price", "")

            # Check payment iframe for saved card
            saved_card = payment.get("saved_card", "")
            if not saved_card:
                for frame in page.frames:
                    if "paymentcomponent" in frame.url or "payment" in frame.url:
                        try:
                            iframe_info = await frame.evaluate(_IFRAME_CARD_DETECT_JS)
                            if iframe_info.get("saved_card"):
                                saved_card = iframe_info["saved_card"]
                                payment["needs_cvv"] = iframe_info.get(
                                    "needs_cvv", True
                                )
                        except Exception:
                            pass
                        break

            if saved_card:
                result["status"] = "SAVED_CARD"
                result["saved_card"] = saved_card
                result["needs_cvv"] = payment.get("needs_cvv", True)
            elif payment.get("is_payment_step"):
                result["status"] = "NEEDS_CARD"
            else:
                result["status"] = "READY_TO_BOOK"

        except Exception as e:
            logger.error("Playwright booking error: %s", e, exc_info=True)
            result["status"] = "ERROR"
            result["error"] = str(e)[:300]
        finally:
            await browser.close()

    return result


# ── Browser Search (Playwright-first, browser-use fallback) ─────────────────


async def execute_browser_search(user_id: str) -> dict[str, Any]:
    """Execute hotel search — Playwright first, browser-use as fallback.

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

    # ── Try Playwright first (fast, stable) ──
    if site == "booking.com":
        storage_state = await browser_service.get_storage_state(
            user_id, site
        )
        if storage_state:
            logger.info("Running Playwright search for user %s on %s",
                        user_id, site)
            try:
                results = await asyncio.wait_for(
                    _execute_playwright_search(
                        storage_state, parsed, site, fetch_details=True,
                    ),
                    timeout=SEARCH_TIMEOUT,
                )
            except TimeoutError:
                logger.warning("Playwright search timed out for user %s",
                               user_id)
                results = []

            if results:
                state["step"] = "awaiting_selection"
                state["results"] = results[:MAX_RESULTS]
                await _set_state(user_id, state)
                text = _format_results_telegram(
                    results[:MAX_RESULTS], site, parsed
                )
                buttons = _build_result_buttons(
                    results[:MAX_RESULTS], flow_id
                )
                return {
                    "action": "results", "text": text, "buttons": buttons
                }
            logger.info("Playwright returned no results, trying GPT-5.4 "
                        "Computer Use")

            # ── GPT-5.4 Computer Use (visual browser control) ──
            try:
                from src.tools.computer_use_booking import (
                    execute_computer_use_search,
                )

                cu_results = await asyncio.wait_for(
                    execute_computer_use_search(
                        storage_state, parsed, site,
                    ),
                    timeout=SEARCH_TIMEOUT,
                )
            except Exception as _cu_err:
                logger.warning("Computer use search failed: %s", _cu_err)
                cu_results = []

            if cu_results:
                state["step"] = "awaiting_selection"
                state["results"] = cu_results[:MAX_RESULTS]
                await _set_state(user_id, state)
                text = _format_results_telegram(
                    cu_results[:MAX_RESULTS], site, parsed
                )
                buttons = _build_result_buttons(
                    cu_results[:MAX_RESULTS], flow_id
                )
                return {
                    "action": "results", "text": text, "buttons": buttons
                }
            logger.info("Computer Use returned no results, falling back to "
                        "browser-use")

    # ── Fallback: browser-use ──
    prompt = _build_search_prompt(site, parsed)

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
    """Navigate to booking form — Playwright first, browser-use fallback.

    Returns dict with: action, text, buttons.
    Actions: "payment_handoff", "sold_out", "login_required", "error"
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

    # ── Playwright-first for booking.com ──
    booking_result = None
    if site == "booking.com":
        try:
            booking_result = await asyncio.wait_for(
                _execute_playwright_booking(storage_state, hotel, parsed),
                timeout=BOOKING_TIMEOUT,
            )
        except TimeoutError:
            logger.warning("Playwright booking timed out for %s", user_id)
        except Exception as e:
            logger.error("Playwright booking error: %s", e, exc_info=True)

        # ── GPT-5.4 Computer Use fallback for booking ──
        if not booking_result or booking_result.get("status") == "ERROR":
            logger.info("Playwright booking failed, trying GPT-5.4 Computer Use")
            try:
                from src.tools.computer_use_booking import (
                    execute_computer_use_booking,
                )

                cu_booking = await asyncio.wait_for(
                    execute_computer_use_booking(
                        storage_state, hotel, parsed
                    ),
                    timeout=BOOKING_TIMEOUT * 2,
                )
                if cu_booking.get("status") not in ("ERROR", None):
                    booking_result = cu_booking
                    booking_result["_source"] = "computer_use"
            except Exception as _cu_err:
                logger.warning("Computer use booking failed: %s", _cu_err)

    if booking_result:
        pw_status = booking_result.get("status", "")
        booking_url = booking_result.get("booking_url", hotel.get("url", ""))
        total_price = (
            booking_result.get("total_price") or hotel.get("total_price", "")
        )
        cancellation = hotel.get("cancellation", "")
        saved_card = booking_result.get("saved_card", "")
        prefilled_name = booking_result.get("prefilled_name", "")

        if pw_status == "SAVED_CARD":
            # Card on file — user just needs to enter CVV
            state["step"] = "payment_handoff"
            state["booking_data"] = booking_result
            await _set_state(user_id, state)

            text = (
                f"<b>Almost done!</b>\n\n"
                f"Hotel: <b>{hotel.get('name', '')}</b>\n"
                f"Total: <b>{total_price}</b>\n"
            )
            if cancellation:
                text += f"Cancellation: {cancellation}\n"
            if prefilled_name:
                text += f"Guest: {prefilled_name}\n"
            text += (
                f"\nYour saved card <b>{saved_card}</b> is ready. "
                "Just enter your CVV to complete the booking."
            )

            buttons = []
            if booking_url:
                buttons.append(
                    {"text": "Complete booking", "url": booking_url}
                )
            buttons.append(
                {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"}
            )
            return {
                "action": "payment_handoff",
                "text": text,
                "buttons": buttons,
            }

        if pw_status == "NEEDS_CARD":
            # No saved card — user must enter card details
            state["step"] = "payment_handoff"
            state["booking_data"] = booking_result
            await _set_state(user_id, state)

            text = (
                f"<b>Card required</b>\n\n"
                f"Hotel: <b>{hotel.get('name', '')}</b>\n"
                f"Total: <b>{total_price}</b>\n"
            )
            if cancellation:
                text += f"Cancellation: {cancellation}\n"
            text += (
                "\nA credit card is required as guarantee (even for free "
                "cancellation). Please enter your card details to complete."
            )

            buttons = []
            if booking_url:
                buttons.append(
                    {"text": "Enter card & complete", "url": booking_url}
                )
            buttons.append(
                {"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"}
            )
            return {
                "action": "payment_handoff",
                "text": text,
                "buttons": buttons,
            }

        if pw_status in ("NOT_ON_BOOKING_PAGE", "NO_URL"):
            logger.warning(
                "Playwright booking didn't reach form: %s", pw_status
            )
            # Fall through to browser-use

    # ── Browser-Use fallback ──
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

    # Default: treat as payment required (booking.com always needs a card)
    booking_url = booking_data.get("booking_url", hotel.get("url", ""))
    final_price = booking_data.get(
        "final_price", hotel.get("total_price", "")
    )
    cancellation = booking_data.get(
        "cancellation_policy", hotel.get("cancellation", "")
    )

    state["step"] = "payment_handoff"
    state["booking_data"] = booking_data
    await _set_state(user_id, state)

    text = (
        f"<b>Card required</b>\n\n"
        f"Hotel: <b>{hotel.get('name', '')}</b>\n"
        f"Total: <b>{final_price}</b>\n"
    )
    if cancellation:
        text += f"Cancellation: {cancellation}\n"
    text += (
        "\nPlease complete the booking using the link below."
    )

    buttons = []
    if booking_url:
        buttons.append({"text": "Complete booking", "url": booking_url})
    buttons.append({"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"})

    return {"action": "payment_handoff", "text": text, "buttons": buttons}


async def confirm_booking(user_id: str) -> dict[str, Any]:
    """Send the booking URL for manual completion.

    Booking sites require card details for confirmation, so this sends
    the payment URL to the user rather than clicking the final button.
    """
    state = await get_booking_state(user_id)
    if not state:
        return {"action": "error", "text": "No booking to confirm."}

    hotel = state.get("selected_hotel", {})
    flow_id = state.get("flow_id", "")
    booking_data = state.get("booking_data", {})
    booking_url = booking_data.get("booking_url", hotel.get("url", ""))
    saved_card = booking_data.get("saved_card", "")
    total_price = (
        booking_data.get("total_price") or hotel.get("total_price", "")
    )

    state["step"] = "payment_handoff"
    await _set_state(user_id, state)

    if saved_card:
        text = (
            f"Your saved card <b>{saved_card}</b> is ready.\n"
            f"Enter your CVV to complete the booking for "
            f"<b>{hotel.get('name', '')}</b> ({total_price})."
        )
    else:
        text = (
            f"Enter your card details to complete the booking for "
            f"<b>{hotel.get('name', '')}</b> ({total_price})."
        )

    buttons = []
    if booking_url:
        buttons.append({"text": "Complete booking", "url": booking_url})
    buttons.append({"text": "Cancel", "callback": f"hotel_cancel:{flow_id}"})

    return {"action": "payment_handoff", "text": text, "buttons": buttons}


async def cancel_flow(user_id: str) -> None:
    """Cancel the active hotel booking flow."""
    await _clear_state(user_id)


# ── Prompt Builders ──────────────────────────────────────────────────────────


def _build_search_prompt(site: str, parsed: dict) -> str:
    """Build the Browser-Use search task prompt with JS DOM extraction."""
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

    # Pick the right JS extraction script for this site
    js_template = _JS_EXTRACT_MAP.get(site, _JS_EXTRACT_GENERIC)
    js_extraction = js_template.format(max_results=MAX_RESULTS)

    return _SEARCH_TASK_PROMPT.format(
        site_url=site_url,
        city=parsed.get("city", ""),
        check_in=parsed.get("check_in", ""),
        check_out=parsed.get("check_out", ""),
        guests=parsed.get("guests", 2),
        filter_section=filter_section or "No specific filters.\n",
        filter_steps=filter_steps or "",
        js_extraction=js_extraction,
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
            "gemini-3.1-flash-lite-preview",
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
            "price_per_night": str(r.get("price_per_night", r.get("price", ""))),
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

        # Parse composite rating strings like "Scored 7.9 7.9Good 1,459 reviews"
        # or "7.9" from JS extraction
        if hotel["rating"] and not hotel["rating"].replace(".", "").isdigit():
            rating_match = re.search(r"(\d+\.?\d*)", hotel["rating"])
            if rating_match:
                # Extract review count if embedded in rating string
                if not hotel["review_count"]:
                    count_match = re.search(
                        r"([\d,]+)\s*review", hotel["rating"]
                    )
                    if count_match:
                        hotel["review_count"] = count_match.group(1)
                hotel["rating"] = rating_match.group(1)

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
        # Show room types from details if available
        if r.get("rooms"):
            for room in r["rooms"][:2]:
                rtype = room.get("type", "")
                rprice = room.get("price", "")
                if rtype:
                    line += f"   Room: {rtype}"
                    if rprice:
                        line += f" — {rprice}"
                    line += "\n"
        if r.get("address"):
            line += f"   {r['address']}\n"

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
