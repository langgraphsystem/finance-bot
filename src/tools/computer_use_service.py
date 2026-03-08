"""Generic OpenAI Computer Use backend for authenticated browser tasks."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from src.core.config import settings
from src.core.llm.clients import openai_client

logger = logging.getLogger(__name__)

VIEWPORT_W = 1440
VIEWPORT_H = 900
DEFAULT_MAX_STEPS = 30
DEFAULT_TIMEOUT_S = 180.0
ACTION_PAUSE_S = 0.8
AFTER_NAVIGATE_PAUSE_S = 2.5
PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

DEFAULT_SYSTEM_PROMPT = """\
You are an authenticated browser agent controlling a real browser.

Your job is to complete the user's task on the requested website.

Rules:
- Close popups, cookie banners, and overlays when needed.
- Use the already logged-in browser session if present.
- If the site requires a new login, MFA, or a CAPTCHA, stop and return exactly:
  LOGIN_REQUIRED
  or
  CAPTCHA_DETECTED
- Do not invent results. Only report what you actually see or completed.
- When you are done, return a concise plain-text summary of the final state.
"""

_SHOPPING_DOMAINS = (
    "amazon.",
    "walmart.",
    "target.",
    "ebay.",
    "bestbuy.",
    "costco.",
    "aliexpress.",
    "ozon.",
    "wildberries.",
)
_FOOD_DOMAINS = (
    "ubereats.",
    "doordash.",
    "grubhub.",
    "instacart.",
    "postmates.",
    "deliveroo.",
    "glovo.",
    "yandexeda.",
)
_TAXI_DOMAINS = (
    "uber.",
    "lyft.",
    "bolt.eu",
    "grab.",
    "careem.",
    "yango.",
)
_TRAVEL_DOMAINS = (
    "booking.",
    "airbnb.",
    "hotels.",
    "expedia.",
    "agoda.",
    "kayak.",
    "skyscanner.",
    "ostrovok.",
)
_ACCOUNT_KEYWORDS = (
    "status",
    "reservation",
    "booking status",
    "trip",
    "order status",
    "my orders",
    "my bookings",
    "track package",
    "refund",
    "account",
    "profile",
    "history",
    "invoice",
    "receipt",
    "заказ",
    "статус",
    "бронь",
    "поездк",
    "аккаунт",
    "истори",
    "проверь",
    "квитанц",
)
_SHOPPING_KEYWORDS = (
    "buy",
    "purchase",
    "order",
    "cart",
    "checkout",
    "add to cart",
    "купи",
    "закажи",
    "товар",
    "корзин",
    "покуп",
    "оформ",
)
_FOOD_KEYWORDS = (
    "food",
    "restaurant",
    "delivery",
    "takeout",
    "meal",
    "groceries",
    "ubereats",
    "doordash",
    "достав",
    "еда",
    "продукт",
    "ресторан",
    "суши",
    "пицц",
)
_TAXI_KEYWORDS = (
    "taxi",
    "ride",
    "cab",
    "uber",
    "lyft",
    "pickup",
    "dropoff",
    "surge",
    "такси",
    "поездк",
    "вызови",
)
_BLOCKED_KEY_COMBOS = {
    frozenset({"CTRL", "L"}),
    frozenset({"CTRL", "TAB"}),
    frozenset({"CTRL", "W"}),
    frozenset({"CTRL", "R"}),
    frozenset({"CTRL", "T"}),
    frozenset({"CTRL", "N"}),
    frozenset({"ALT", "D"}),
    frozenset({"ALT", "LEFT"}),
    frozenset({"ALT", "RIGHT"}),
    frozenset({"F5"}),
    frozenset({"F6"}),
}
_KEY_MAP = {
    "ENTER": "Enter",
    "RETURN": "Enter",
    "TAB": "Tab",
    "ESCAPE": "Escape",
    "ESC": "Escape",
    "SPACE": " ",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "CTRL": "Control",
    "CONTROL": "Control",
    "ALT": "Alt",
    "SHIFT": "Shift",
    "ARROWUP": "ArrowUp",
    "ARROWDOWN": "ArrowDown",
    "ARROWLEFT": "ArrowLeft",
    "ARROWRIGHT": "ArrowRight",
    "UP": "ArrowUp",
    "DOWN": "ArrowDown",
    "LEFT": "ArrowLeft",
    "RIGHT": "ArrowRight",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PAGEDOWN": "PageDown",
}


def _item_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type", ""))
    return str(getattr(item, "type", ""))


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _classify_task(site: str, task: str) -> str:
    domain = site.lower()
    lower = task.lower()

    if any(marker in domain for marker in _FOOD_DOMAINS) or any(
        marker in lower for marker in _FOOD_KEYWORDS
    ):
        return "food_delivery"

    if any(marker in domain for marker in _TAXI_DOMAINS) or any(
        marker in lower for marker in _TAXI_KEYWORDS
    ):
        return "taxi"

    if any(marker in domain for marker in _TRAVEL_DOMAINS):
        return "travel"

    if any(marker in lower for marker in _ACCOUNT_KEYWORDS):
        return "account"

    if any(marker in domain for marker in _SHOPPING_DOMAINS) or any(
        marker in lower for marker in _SHOPPING_KEYWORDS
    ):
        return "shopping"

    return "generic"


def _key_combo(keys: list[Any]) -> str | None:
    normalized = [str(key).upper() for key in keys if str(key).strip()]
    if not normalized:
        return None

    if frozenset(normalized) in _BLOCKED_KEY_COMBOS:
        return None

    mapped = [_KEY_MAP.get(key, str(key).title()) for key in normalized]
    if len(mapped) == 1:
        return mapped[0]
    return "+".join(mapped)


def build_system_prompt(site: str, task: str) -> str:
    profile = _classify_task(site, task)
    domain = site.lower()

    profile_instructions = {
        "shopping": """\
Task type: shopping / product purchase.

What to do:
- Find the exact product or the closest clearly matching option.
- Check price, seller, quantity, shipping cost, delivery date, and cart / checkout state.
- If the product is ambiguous, compare the top options and explain the differences.
- If the user already asked to buy/order, proceed through cart and checkout when possible.
- If anything is unclear at the final irreversible step, stop on the review page and summarize.""",
        "food_delivery": """\
Task type: food / grocery delivery.

What to do:
- Use the saved address and saved payment method if already available on the site.
- Find the requested restaurant or store, choose matching items, and note substitutions if needed.
- Check subtotal, fees, taxes, tip, ETA, and the final checkout state.
- If the exact item is unavailable, report the closest options instead of inventing a replacement.
- If the order is ready to place, say whether it was placed or is waiting on final review.""",
        "taxi": """\
Task type: taxi / ride-hailing.

What to do:
- Identify pickup and dropoff from the task or from saved locations on the site.
- Compare relevant ride options if more than one appears.
- Check ETA, fare, surge / extra fees, and booking status.
- If the ride is not yet confirmed, stop on the final confirmation step and report what remains.
- If the task is explicit and the site confirms the ride, report the confirmed ride details.""",
        "travel": """\
Task type: travel / reservations.

What to do:
- Review reservations, prices, dates, policies, travelers, and confirmation state.
- For search flows, return the strongest matching options with price and cancellation terms.
- For booking-management flows, report the exact reservation state and next actionable step.
- Stop immediately if the site requires a fresh login or verification.""",
        "account": """\
Task type: authenticated account lookup.

What to do:
- Read the account page carefully and summarize the exact status you see.
- Prefer order status, reservations, subscriptions, messages, invoices, refunds, or trip history.
- Do not make changes unless the task explicitly asks for one.""",
        "generic": """\
Task type: generic authenticated website task.

What to do:
- Navigate carefully, inspect the relevant page, and complete the user's task if it is unambiguous.
- Summarize the final state and any important values you observed.""",
    }

    output_expectations = {
        "shopping": """\
Return plain text with these fields when available:
Status:
Site:
Item:
Price:
Shipping:
Taxes/Fees:
Delivery:
Checkout state:
URL:""",
        "food_delivery": """\
Return plain text with these fields when available:
Status:
Site:
Store/Restaurant:
Items:
Subtotal:
Fees/Tip:
ETA:
Checkout state:
URL:""",
        "taxi": """\
Return plain text with these fields when available:
Status:
Site:
Ride type:
Pickup:
Dropoff:
ETA:
Fare:
Fees/Surge:
Confirmation state:
URL:""",
        "travel": """\
Return plain text with these fields when available:
Status:
Site:
Reservation / Option:
Dates:
Price:
Policy:
Next step:
URL:""",
        "account": """\
Return plain text with these fields when available:
Status:
Site:
Subject:
Current state:
Important details:
Next step:
URL:""",
        "generic": """\
Return a concise plain-text summary of the final state.
Include the final URL when it helps the user verify the result.""",
    }

    site_line = f"Current site: {domain}" if domain else "Current site: not specified"
    return (
        f"{DEFAULT_SYSTEM_PROMPT.strip()}\n\n"
        f"{site_line}\n\n"
        f"{profile_instructions[profile]}\n\n"
        "Safety and accuracy rules:\n"
        "- Prefer saved carts, saved addresses, and already-signed-in state when available.\n"
        "- Do not invent prices, ETAs, fees, or confirmation numbers.\n"
        "- If the task becomes ambiguous, say exactly what is missing.\n"
        "- If the site asks for a new login, MFA, phone verification, or CAPTCHA, "
        "stop with the exact sentinel.\n\n"
        f"{output_expectations[profile]}"
    )


async def _take_screenshot(page: Any) -> str:
    png_bytes = await page.screenshot(type="png", full_page=False)
    return base64.b64encode(png_bytes).decode("utf-8")


async def _execute_actions(page: Any, actions: list[Any]) -> None:
    for action in actions:
        action_type = _item_type(action)

        def _get(key: str, default: Any = 0) -> Any:
            return _item_value(action, key, default)

        try:
            if action_type == "click":
                await page.mouse.click(
                    _get("x"),
                    _get("y"),
                    button=_get("button", "left"),
                )
            elif action_type == "double_click":
                await page.mouse.dblclick(
                    _get("x"),
                    _get("y"),
                    button=_get("button", "left"),
                )
            elif action_type == "scroll":
                await page.mouse.move(_get("x"), _get("y"))
                await page.mouse.wheel(
                    _get("scrollX", _get("scroll_x", 0)),
                    _get("scrollY", _get("scroll_y", 0)),
                )
            elif action_type == "type":
                await page.keyboard.type(str(_get("text", "")))
            elif action_type == "keypress":
                keys = _get("keys", [])
                if not isinstance(keys, list):
                    keys = [keys]
                combo = _key_combo(keys)
                if combo:
                    await page.keyboard.press(combo)
                else:
                    logger.info("Skipping blocked or empty keypress combo: %s", keys)
            elif action_type == "drag":
                await page.mouse.move(_get("startX"), _get("startY"))
                await page.mouse.down()
                await page.mouse.move(_get("endX"), _get("endY"))
                await page.mouse.up()
            elif action_type == "wait":
                await asyncio.sleep(2.0)
        except Exception as e:
            logger.warning("Computer-use action %s failed: %s", action_type, e)

    await asyncio.sleep(ACTION_PAUSE_S)


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        item_type = _item_type(item)
        if item_type in {"text", "output_text"}:
            text = _item_value(item, "text", "")
            if text:
                chunks.append(str(text))
        elif item_type == "message":
            for content in _item_value(item, "content", []) or []:
                if _item_type(content) in {"output_text", "text"}:
                    text = _item_value(content, "text", "")
                    if text:
                        chunks.append(str(text))

    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _get_computer_call(response: Any) -> Any | None:
    for item in getattr(response, "output", []) or []:
        if _item_type(item) == "computer_call":
            return item
    return None


def _computer_tool() -> dict[str, str]:
    return {"type": "computer"}


async def execute_task(
    *,
    storage_state: dict | None,
    site: str,
    task: str,
    start_url: str | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Run a real browser task via OpenAI Computer Use."""
    if not settings.openai_api_key:
        return {
            "success": False,
            "result": "OpenAI API key is not configured.",
            "engine": "openai_computer_use",
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "result": "Playwright is not available.",
            "engine": "openai_computer_use",
        }

    client = openai_client()
    current_model = model or settings.openai_computer_use_model
    target_url = start_url or f"https://{site}"
    resolved_system_prompt = system_prompt or build_system_prompt(site, task)
    start_time = time.monotonic()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
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
                user_agent=PLAYWRIGHT_UA,
            )
            page = await context.new_page()
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

            screenshot_b64 = await _take_screenshot(page)
            response = await client.responses.create(
                model=current_model,
                tools=[_computer_tool()],
                reasoning={"effort": "medium"},
                input=[
                    {"role": "developer", "content": resolved_system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": task},
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{screenshot_b64}",
                                "detail": "auto",
                            },
                        ],
                    },
                ],
            )

            for _ in range(max_steps):
                if time.monotonic() - start_time > timeout:
                    return {
                        "success": False,
                        "result": f"Computer-use task timed out after {timeout}s.",
                        "engine": "openai_computer_use",
                    }

                computer_call = _get_computer_call(response)
                if computer_call is None:
                    break

                actions = _item_value(computer_call, "actions", []) or []
                await _execute_actions(page, actions)

                if any(
                    _item_type(action) in {"click", "double_click", "keypress"}
                    for action in actions
                ):
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

                screenshot_b64 = await _take_screenshot(page)
                response = await client.responses.create(
                    model=current_model,
                    tools=[_computer_tool()],
                    reasoning={"effort": "medium"},
                    previous_response_id=response.id,
                    input=[
                        {
                            "type": "computer_call_output",
                            "call_id": _item_value(computer_call, "call_id", ""),
                            "output": {
                                "type": "computer_screenshot",
                                "image_url": f"data:image/png;base64,{screenshot_b64}",
                                "detail": "auto",
                            },
                        }
                    ],
                )

            final_text = _extract_output_text(response)
            updated_state = await context.storage_state()
            return {
                "success": bool(final_text),
                "result": final_text or "Computer-use task completed without output.",
                "engine": "openai_computer_use",
                "storage_state": updated_state,
                "url": page.url,
            }
        except Exception as e:
            logger.exception("OpenAI computer-use task failed: %s", task[:120])
            return {
                "success": False,
                "result": f"Computer-use task failed: {e}",
                "engine": "openai_computer_use",
            }
        finally:
            await browser.close()
