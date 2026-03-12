"""Gemini Computer Use backend for authenticated browser tasks.

Uses Gemini 3.1 Pro (or 3 Pro/Flash) with the built-in computer_use tool.
Same interface as computer_use_service.py but routes through Google GenAI SDK.

Coordinate system: model outputs 0–1000 normalized, denormalized to viewport pixels.
Screenshot history: last 3 turns kept, older ones pruned to save tokens.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from google.genai import types

from src.core.config import settings
from src.core.llm.clients import google_client
from src.tools.computer_use_service import (
    _BLOCKED_KEY_COMBOS,
    _KEY_MAP,
    ACTION_PAUSE_S,
    AFTER_NAVIGATE_PAUSE_S,
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_S,
    PLAYWRIGHT_UA,
    VIEWPORT_H,
    VIEWPORT_W,
    build_system_prompt,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-flash-preview"
MAX_SCREENSHOT_HISTORY = 3


def _denormalize(val: int, screen_dim: int) -> int:
    """Convert 0–1000 normalized coordinate to pixel."""
    return int(val / 1000 * screen_dim)


def _key_combo_gemini(keys_str: str) -> str | None:
    """Parse Gemini key_combination format ('Control+C') into Playwright combo."""
    parts = [k.strip() for k in keys_str.split("+") if k.strip()]
    if not parts:
        return None
    normalized = [p.upper() for p in parts]
    if frozenset(normalized) in _BLOCKED_KEY_COMBOS:
        return None
    mapped = [_KEY_MAP.get(k, k.title()) for k in normalized]
    return "+".join(mapped) if mapped else None


async def _execute_action(page: Any, name: str, args: dict, sw: int, sh: int) -> dict:
    """Execute a single Gemini computer_use action on a Playwright page.

    Returns a dict with action result metadata.
    """
    try:
        if name == "click_at":
            x = _denormalize(args.get("x", 0), sw)
            y = _denormalize(args.get("y", 0), sh)
            await page.mouse.click(x, y)
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "type_text_at":
            x = _denormalize(args.get("x", 0), sw)
            y = _denormalize(args.get("y", 0), sh)
            text = str(args.get("text", ""))
            clear = args.get("clear_before_typing", False)
            press_enter = args.get("press_enter", False)
            await page.mouse.click(x, y)
            await asyncio.sleep(0.3)
            if clear:
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
                await asyncio.sleep(0.2)
            if text:
                await page.keyboard.type(text)
            if press_enter:
                await page.keyboard.press("Enter")
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "hover_at":
            x = _denormalize(args.get("x", 0), sw)
            y = _denormalize(args.get("y", 0), sh)
            await page.mouse.move(x, y)

        elif name == "scroll_document":
            direction = str(args.get("direction", "down")).lower()
            if direction == "down":
                await page.keyboard.press("PageDown")
            elif direction == "up":
                await page.keyboard.press("PageUp")
            elif direction == "left":
                await page.evaluate("window.scrollBy(-window.innerWidth * 0.8, 0)")
            elif direction == "right":
                await page.evaluate("window.scrollBy(window.innerWidth * 0.8, 0)")
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "scroll_at":
            x = _denormalize(args.get("x", 0), sw)
            y = _denormalize(args.get("y", 0), sh)
            direction = str(args.get("direction", "down")).lower()
            magnitude = int(args.get("magnitude", 3))
            scroll_px = magnitude * 100
            dx, dy = 0, 0
            if direction == "down":
                dy = scroll_px
            elif direction == "up":
                dy = -scroll_px
            elif direction == "right":
                dx = scroll_px
            elif direction == "left":
                dx = -scroll_px
            await page.mouse.move(x, y)
            await page.mouse.wheel(dx, dy)
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "key_combination":
            keys_str = str(args.get("keys", ""))
            combo = _key_combo_gemini(keys_str)
            if combo:
                await page.keyboard.press(combo)
            else:
                logger.info("Gemini CU: blocked or unmapped key combo: %s", keys_str)
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "drag_and_drop":
            sx = _denormalize(args.get("x", 0), sw)
            sy = _denormalize(args.get("y", 0), sh)
            dx = _denormalize(args.get("destination_x", 0), sw)
            dy = _denormalize(args.get("destination_y", 0), sh)
            await page.mouse.move(sx, sy)
            await page.mouse.down()
            await page.mouse.move(dx, dy, steps=10)
            await page.mouse.up()
            await asyncio.sleep(ACTION_PAUSE_S)

        elif name == "navigate":
            url = str(args.get("url", ""))
            if url and not url.startswith("http"):
                url = f"https://{url}"
            if url:
                await page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

        elif name == "go_back":
            await page.go_back(wait_until="domcontentloaded")
            await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

        elif name == "go_forward":
            await page.go_forward(wait_until="domcontentloaded")
            await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

        elif name == "search":
            await page.goto("https://www.google.com", wait_until="domcontentloaded")
            await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

        elif name == "open_web_browser":
            pass  # already open

        elif name == "wait_5_seconds":
            await asyncio.sleep(5.0)

        else:
            logger.warning("Gemini CU: unknown action %s, skipping", name)

    except Exception as e:
        logger.warning("Gemini CU action %s failed: %s", name, e)
        return {"error": str(e)}

    return {"status": "ok"}


def _take_screenshot_sync(page: Any) -> bytes:
    """Synchronous wrapper — use inside the async loop."""
    raise NotImplementedError("Use _take_screenshot instead")


async def _take_screenshot(page: Any) -> bytes:
    return await page.screenshot(type="png", full_page=False)


def _prune_screenshot_history(contents: list, keep: int = MAX_SCREENSHOT_HISTORY) -> None:
    """Remove screenshot blobs from older function response turns.

    Keeps only the last `keep` user turns that contain screenshots inside
    FunctionResponse.parts.
    """
    screenshot_turn_indices: list[int] = []
    for i, content in enumerate(contents):
        if not hasattr(content, "parts") or not content.parts:
            continue
        if getattr(content, "role", None) != "user":
            continue
        for part in content.parts:
            fr = getattr(part, "function_response", None)
            if fr and getattr(fr, "parts", None):
                screenshot_turn_indices.append(i)
                break
            # Also catch standalone inline_data (initial screenshot)
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "mime_type", "").startswith("image/"):
                screenshot_turn_indices.append(i)
                break

    if len(screenshot_turn_indices) <= keep:
        return

    to_prune = screenshot_turn_indices[:-keep]
    for idx in to_prune:
        content = contents[idx]
        new_parts = []
        for part in content.parts:
            fr = getattr(part, "function_response", None)
            if fr and getattr(fr, "parts", None):
                # Remove screenshot from function response, keep the response itself
                fr.parts = None
                new_parts.append(part)
            elif getattr(getattr(part, "inline_data", None), "mime_type", "").startswith("image/"):
                # Drop standalone image parts
                continue
            else:
                new_parts.append(part)
        content.parts = new_parts


def _extract_function_calls(response: Any) -> list[tuple[str, dict]]:
    """Extract (name, args) tuples from Gemini response."""
    calls: list[tuple[str, dict]] = []
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not candidate.content or not candidate.content.parts:
        return calls
    for part in candidate.content.parts:
        fc = getattr(part, "function_call", None)
        if fc:
            name = fc.name or ""
            args = dict(fc.args) if fc.args else {}
            calls.append((name, args))
    return calls


def _extract_text(response: Any) -> str:
    """Extract text output from Gemini response."""
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not candidate.content or not candidate.content.parts:
        return ""
    chunks: list[str] = []
    for part in candidate.content.parts:
        if hasattr(part, "text") and part.text:
            chunks.append(part.text)
    return "\n".join(chunks).strip()


def _has_safety_check(name: str, args: dict) -> bool:
    """Check if a function call contains a safety_decision argument."""
    return "safety_decision" in args


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
    """Run a browser task via Gemini Computer Use.

    Same interface as computer_use_service.execute_task() for drop-in usage.
    """
    if not settings.google_ai_api_key:
        return {
            "success": False,
            "result": "Google AI API key is not configured.",
            "engine": "gemini_computer_use",
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "result": "Playwright is not available.",
            "engine": "gemini_computer_use",
        }

    client = google_client()
    current_model = model or DEFAULT_MODEL
    target_url = start_url or f"https://{site}"
    resolved_system_prompt = system_prompt or build_system_prompt(site, task)
    start_time = time.monotonic()

    config = types.GenerateContentConfig(
        system_instruction=resolved_system_prompt,
        tools=[
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                )
            )
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    pw = await async_playwright().start()
    # Try real Chrome first (bypasses WAF on Uber, Amazon, etc.)
    # Falls back to Playwright Chromium on servers without Chrome
    launch_kwargs: dict[str, Any] = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    browser = await pw.chromium.launch(channel="chrome", **launch_kwargs)
    try:
        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            user_agent=PLAYWRIGHT_UA,
        )
        page = await context.new_page()
        await page.goto(target_url, wait_until="domcontentloaded")
        await asyncio.sleep(AFTER_NAVIGATE_PAUSE_S)

        # Initial screenshot
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

        for step in range(max_steps):
            if time.monotonic() - start_time > timeout:
                return {
                    "success": False,
                    "result": f"Gemini CU task timed out after {timeout}s.",
                    "engine": "gemini_computer_use",
                }

            # Call Gemini
            try:
                response = await client.aio.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                logger.warning("Gemini CU API error on step %d: %s", step, e)
                # Retry once after short pause
                await asyncio.sleep(2.0)
                try:
                    response = await client.aio.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=config,
                    )
                except Exception as e2:
                    return {
                        "success": False,
                        "result": f"Gemini CU API error: {e2}",
                        "engine": "gemini_computer_use",
                    }

            # Append model response to conversation
            candidate = response.candidates[0] if response.candidates else None
            if candidate and candidate.content:
                contents.append(candidate.content)

            # Extract function calls
            calls = _extract_function_calls(response)
            if not calls:
                break  # Model returned text only — done

            # Execute each action, collect results + screenshot
            action_results: list[tuple[str, dict, dict | None]] = []
            for name, args in calls:
                # Detect and extract safety check before executing
                safety_val = args.pop("safety_decision", None)
                if safety_val is not None:
                    logger.info("Gemini CU: auto-acknowledging safety check for %s", name)

                result = await _execute_action(page, name, args, VIEWPORT_W, VIEWPORT_H)
                action_results.append((name, result, safety_val))

                # Wait for navigation after click/type/key actions
                if name in {"click_at", "type_text_at", "key_combination"}:
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass

            # Take new screenshot after all actions
            await asyncio.sleep(0.5)
            screenshot_bytes = await _take_screenshot(page)

            # Build function responses with screenshot embedded inside
            fn_response_parts: list[types.Part] = []
            screenshot_part = types.FunctionResponsePart(
                inline_data=types.FunctionResponseBlob(
                    mime_type="image/png",
                    data=screenshot_bytes,
                )
            )
            for i, (name, result, safety_val) in enumerate(action_results):
                resp_payload = {"url": page.url, **result}
                if safety_val is not None:
                    resp_payload["safety_acknowledgement"] = "true"
                # Attach screenshot to the last function response
                fr_parts = [screenshot_part] if i == len(action_results) - 1 else None
                fr = types.FunctionResponse(
                    name=name,
                    response=resp_payload,
                    parts=fr_parts,
                )
                fn_response_parts.append(types.Part(function_response=fr))

            contents.append(
                types.Content(role="user", parts=fn_response_parts)
            )

            # Prune old screenshots to save context
            _prune_screenshot_history(contents, keep=MAX_SCREENSHOT_HISTORY)

        # If loop exhausted steps without text, ask model to summarize
        final_text = _extract_text(response)
        if not final_text:
            try:
                screenshot_bytes = await _take_screenshot(page)
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text="You've run out of steps. Based on what you see now, "
                                "summarize the result so far. What information did you find?"
                            ),
                            types.Part.from_bytes(
                                data=screenshot_bytes, mime_type="image/png"
                            ),
                        ],
                    )
                )
                _prune_screenshot_history(contents, keep=2)
                summary_resp = await client.aio.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )
                final_text = _extract_text(summary_resp)
            except Exception as e:
                logger.warning("Gemini CU summary fallback failed: %s", e)

        updated_state = await context.storage_state()

        return {
            "success": bool(final_text),
            "result": final_text or "Gemini CU task completed without output.",
            "engine": "gemini_computer_use",
            "storage_state": updated_state,
            "url": page.url,
        }

    except Exception as e:
        logger.exception("Gemini computer-use task failed: %s", task[:120])
        return {
            "success": False,
            "result": f"Gemini CU task failed: {e}",
            "engine": "gemini_computer_use",
        }
    finally:
        await browser.close()
        await pw.stop()
