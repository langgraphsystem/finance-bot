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


def _item_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type", ""))
    return str(getattr(item, "type", ""))


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


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
                for key in keys:
                    await page.keyboard.press(" " if key == "SPACE" else str(key))
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
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
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
                    {"role": "developer", "content": system_prompt},
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
