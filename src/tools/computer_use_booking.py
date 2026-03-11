"""Gemini Computer Use integration for hotel booking on booking.com.

Flow:
1. Launch Playwright with user's saved session
2. Navigate to booking.com search URL
3. Take screenshot → send to Gemini with computer_use tool
4. Gemini returns function_calls (click_at/type_text_at/scroll/etc.)
5. Execute actions via Playwright → take new screenshot → repeat
6. Extract structured hotel list when Gemini is done
7. For booking: stop before final payment confirmation

Gemini sees the real browser UI — handles popups, CAPTCHAs,
dynamic layouts that JS extraction misses.

Viewport: 1440×900
"""

import asyncio
import json
import logging
import re
import time
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VIEWPORT_W = 1440
VIEWPORT_H = 900
MAX_STEPS = 40          # max computer_call rounds per task
STEP_TIMEOUT = 300.0    # total timeout for entire CU session (seconds)
ACTION_PAUSE = 0.8      # pause after each action group (seconds)
AFTER_NAVIGATE_PAUSE = 3.0   # pause after page navigation

_PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

# ── System Prompts ────────────────────────────────────────────────────────────

_SEARCH_SYSTEM = """\
You are a hotel search assistant controlling a real web browser.
Your job: search booking.com for hotels and extract results as JSON.

RULES:
- Close all popups, cookie banners, login prompts before searching
- After getting search results, extract hotel data from the page
- When you have 3-5 hotels extracted, respond with JSON — do NOT keep clicking
- STOP immediately if you see a CAPTCHA → respond: CAPTCHA_DETECTED
- STOP if the site asks to log in → respond: LOGIN_REQUIRED
- STOP if no hotels found → respond: NO_RESULTS

OUTPUT FORMAT (when done):
Return a JSON array — nothing else:
[{"name": "...", "price_per_night": "...", "rating": "...",
  "review_count": "...", "distance": "...", "cancellation": "...",
  "description": "...", "url": "..."}]
"""

_BOOKING_SYSTEM = """\
You are a hotel booking assistant controlling a real web browser.
Your job: navigate to the hotel page, select the cheapest room,
advance through the booking form — but STOP before final confirmation.

RULES:
- Close all popups, cookie banners, login prompts
- Select the cheapest available room
- Click Reserve/Book to open the booking form
- Fill required fields if they are empty (use the guest info provided)
- Navigate through booking steps until you reach the PAYMENT page
- STOP at the payment page — do NOT click final "Complete Booking"
- STOP if you see CAPTCHA → respond: CAPTCHA_DETECTED
- STOP if LOGIN_REQUIRED

OUTPUT FORMAT (when stopped at payment):
Return JSON:
{"status": "READY_TO_BOOK",
 "total_price": "...",
 "room_type": "...",
 "cancellation_policy": "...",
 "payment_type": "pay_at_hotel or prepay_required",
 "saved_card": "Visa ****4242 or null",
 "booking_url": "current page URL",
 "notes": "..."}

If sold out: {"status": "SOLD_OUT"}
If login needed: {"status": "LOGIN_REQUIRED"}
"""


# ── Core Computer Use Loop ────────────────────────────────────────────────────


async def _take_screenshot(page: Any) -> bytes:
    """Capture page screenshot as raw PNG bytes."""
    return await page.screenshot(type="png", full_page=False)


async def _run_computer_use_loop(
    page: Any,
    task: str,
    system_prompt: str,
    model: str | None = None,
    max_steps: int = MAX_STEPS,
    timeout: float = STEP_TIMEOUT,
) -> str:
    """Core Gemini Computer Use loop for booking tasks.

    Takes a screenshot → sends to Gemini → executes actions → repeat.
    Returns the model's final text output when it stops issuing function_calls.
    """
    from google.genai import types

    from src.core.llm.clients import google_client
    from src.tools.gemini_computer_use import (
        _execute_action,
        _extract_function_calls,
        _extract_text,
        _prune_screenshot_history,
    )

    client = google_client()
    current_model = model or settings.gemini_computer_use_model
    start_time = time.monotonic()

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                )
            )
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    screenshot_bytes = await _take_screenshot(page)

    contents: list[Any] = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=task),
                types.Part.from_bytes(data=screenshot_bytes, mime_type="image/png"),
            ],
        )
    ]

    response = None
    for step in range(max_steps):
        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            logger.warning("Gemini CU booking loop timed out after %.1fs", elapsed)
            break

        try:
            response = await client.aio.models.generate_content(
                model=current_model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            logger.warning("Gemini CU booking API error on step %d: %s", step, e)
            await asyncio.sleep(2.0)
            try:
                response = await client.aio.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )
            except Exception as e2:
                logger.error("Gemini CU booking API retry failed: %s", e2)
                break

        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content:
            contents.append(candidate.content)

        calls = _extract_function_calls(response)
        if not calls:
            logger.info("Gemini CU booking finished after %d steps", step)
            break

        logger.debug("Gemini CU booking step %d/%d: %d actions", step + 1, max_steps, len(calls))

        action_results: list[tuple[str, dict]] = []
        for name, args in calls:
            args.pop("safety_decision", None)
            result = await _execute_action(page, name, args, VIEWPORT_W, VIEWPORT_H)
            action_results.append((name, result))

            if name in {"click_at", "type_text_at", "key_combination"}:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(AFTER_NAVIGATE_PAUSE)

        await asyncio.sleep(0.5)
        screenshot_bytes = await _take_screenshot(page)

        fn_parts: list[types.Part] = []
        for name, result in action_results:
            fn_parts.append(
                types.Part.from_function_response(name=name, response={"url": page.url, **result})
            )
        fn_parts.append(types.Part.from_bytes(data=screenshot_bytes, mime_type="image/png"))
        contents.append(types.Content(role="user", parts=fn_parts))

        _prune_screenshot_history(contents, keep=3)

    if response is None:
        return ""
    return _extract_text(response)


# ── Search ────────────────────────────────────────────────────────────────────


async def execute_computer_use_search(
    storage_state: dict,
    parsed: dict,
    site: str = "booking.com",
    max_steps: int = MAX_STEPS,
    timeout: float = STEP_TIMEOUT,
) -> list[dict[str, Any]]:
    """Search hotels on booking.com using GPT-5.4 Computer Use.

    Launches a headed-or-headless Playwright browser with the user's saved
    session, then lets GPT-5.4 control it visually to search and extract
    hotel results.

    Returns list of hotel dicts (empty on failure/CAPTCHA).
    """
    from urllib.parse import quote

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed")
        return []

    city = parsed.get("city", "")
    check_in = parsed.get("check_in", "")
    check_out = parsed.get("check_out", "")
    guests = parsed.get("guests", 2)
    budget = parsed.get("budget_per_night")

    # Build direct search URL (lands model on results page immediately)
    params = [
        f"ss={quote(city)}",
        f"checkin={check_in}",
        f"checkout={check_out}",
        f"group_adults={guests}",
        "no_rooms=1",
        "group_children=0",
    ]
    if budget:
        params.append(f"nflt=price%3DUSD-min-{budget}-1")
    search_url = f"https://www.booking.com/searchresults.html?{'&'.join(params)}"

    task = (
        f"I'm on booking.com searching for hotels.\n"
        f"Destination: {city}\n"
        f"Check-in: {check_in}, Check-out: {check_out}\n"
        f"Guests: {guests}\n"
        f"{'Budget: up to $' + str(budget) + '/night' if budget else ''}\n\n"
        f"Close any popups. Wait for the hotel list to load.\n"
        f"Extract the top 5 hotels and return as JSON array."
    )

    hotels: list[dict[str, Any]] = []

    async with async_playwright() as p:
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
                viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
                user_agent=_PLAYWRIGHT_UA,
            )
            page = await context.new_page()

            # Navigate to search results
            logger.info("CU search: navigating to %s", search_url[:80])
            await page.goto(search_url, wait_until="domcontentloaded")
            await asyncio.sleep(3.0)

            # Run Computer Use loop
            raw_output = await _run_computer_use_loop(
                page=page,
                task=task,
                system_prompt=_SEARCH_SYSTEM,
                max_steps=max_steps,
                timeout=timeout,
            )

            logger.debug("CU search raw output (%.200s...)", raw_output)

            # Parse output
            if "CAPTCHA_DETECTED" in raw_output:
                logger.warning("CU search: CAPTCHA detected")
                return []
            if "LOGIN_REQUIRED" in raw_output:
                logger.warning("CU search: LOGIN_REQUIRED")
                return []
            if "NO_RESULTS" in raw_output:
                logger.info("CU search: no results")
                return []

            hotels = _parse_cu_hotel_results(raw_output)
            logger.info("CU search extracted %d hotels", len(hotels))

        except Exception as e:
            logger.exception("Computer use search failed: %s", e)
        finally:
            await browser.close()

    return hotels


def _parse_cu_hotel_results(raw: str) -> list[dict[str, Any]]:
    """Extract JSON hotel array from GPT-5.4 Computer Use output."""
    # Try to find JSON array in the output
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        if not isinstance(data, list):
            return []
        hotels = []
        for item in data:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            hotels.append({
                "name": str(item.get("name", "")),
                "price_per_night": str(item.get("price_per_night", "")),
                "total_price": str(item.get("total_price", "")),
                "rating": str(item.get("rating", "")),
                "review_count": str(item.get("review_count", "")),
                "distance": str(item.get("distance", "")),
                "amenities": item.get("amenities", []),
                "cancellation": str(item.get("cancellation", "")),
                "description": str(item.get("description", "")),
                "url": str(item.get("url", "")),
            })
        return hotels
    except (json.JSONDecodeError, ValueError):
        return []


# ── Booking ───────────────────────────────────────────────────────────────────


async def execute_computer_use_booking(
    storage_state: dict,
    hotel: dict,
    parsed: dict,
    guest_info: dict | None = None,
    site: str = "booking.com",
    max_steps: int = MAX_STEPS,
    timeout: float = STEP_TIMEOUT,
) -> dict[str, Any]:
    """Book a hotel using GPT-5.4 Computer Use.

    Navigates to the hotel, selects cheapest room, fills the booking form,
    and STOPS before final payment confirmation.

    Returns dict with: status, total_price, room_type, cancellation_policy,
                       payment_type, saved_card, booking_url, notes.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed")
        return {"status": "ERROR", "error": "playwright not installed"}

    hotel_name = hotel.get("name", "the hotel")
    hotel_url = hotel.get("url", "")
    check_in = parsed.get("check_in", "")
    check_out = parsed.get("check_out", "")
    guests = parsed.get("guests", 2)

    guest_name = (guest_info or {}).get("name", "")
    guest_email = (guest_info or {}).get("email", "")

    guest_section = ""
    if guest_name:
        guest_section += f"Guest name: {guest_name}\n"
    if guest_email:
        guest_section += f"Guest email: {guest_email}\n"

    task = (
        f"Book this hotel: {hotel_name}\n"
        f"URL: {hotel_url}\n"
        f"Check-in: {check_in}, Check-out: {check_out}\n"
        f"Guests: {guests}\n"
        f"{guest_section}\n"
        f"Select the cheapest available room.\n"
        f"Navigate through the booking form.\n"
        f"STOP at the payment page — do NOT confirm the booking.\n"
        f"Return the booking status JSON."
    )

    result: dict[str, Any] = {"status": "ERROR"}

    async with async_playwright() as p:
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
                viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
                user_agent=_PLAYWRIGHT_UA,
            )
            page = await context.new_page()

            # Navigate to hotel page
            start_url = hotel_url or "https://www.booking.com"
            logger.info("CU booking: navigating to %s", start_url[:80])
            await page.goto(start_url, wait_until="domcontentloaded")
            await asyncio.sleep(3.0)

            # Run Computer Use loop
            raw_output = await _run_computer_use_loop(
                page=page,
                task=task,
                system_prompt=_BOOKING_SYSTEM,
                max_steps=max_steps,
                timeout=timeout,
            )

            logger.debug("CU booking raw output (%.300s...)", raw_output)

            # Parse output
            parsed_result = _parse_cu_booking_result(raw_output)
            result.update(parsed_result)

        except Exception as e:
            logger.exception("Computer use booking failed: %s", e)
            result["error"] = str(e)[:300]
        finally:
            await browser.close()

    return result


def _parse_cu_booking_result(raw: str) -> dict[str, Any]:
    """Extract booking status JSON from GPT-5.4 Computer Use output."""
    if "CAPTCHA_DETECTED" in raw:
        return {"status": "CAPTCHA"}
    if "LOGIN_REQUIRED" in raw:
        return {"status": "LOGIN_REQUIRED"}
    if "SOLD_OUT" in raw:
        return {"status": "SOLD_OUT"}

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"status": "ERROR", "error": "no JSON in output"}
    try:
        data = json.loads(match.group(0))
        return {
            "status": data.get("status", "READY_TO_BOOK"),
            "total_price": data.get("total_price", ""),
            "price_per_night": data.get("price_per_night", ""),
            "room_type": data.get("room_type", ""),
            "cancellation_policy": data.get("cancellation_policy", ""),
            "payment_type": data.get("payment_type", ""),
            "saved_card": data.get("saved_card"),
            "booking_url": data.get("booking_url", ""),
            "notes": data.get("notes", ""),
        }
    except (json.JSONDecodeError, ValueError):
        return {"status": "ERROR", "error": "invalid JSON", "raw": raw[:500]}
