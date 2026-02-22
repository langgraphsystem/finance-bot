"""Browser automation tool with Browser-Use primary and Playwright fallback.

Primary engine:
- Browser-Use agent (LLM-driven navigation and actions)

Fallback engine:
- Playwright (read-only page retrieval and extraction)

This keeps web features available even when Browser-Use is not installed
or fails at runtime.
"""

import asyncio
import logging
import os
import re
import tempfile
from typing import Any
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

BROWSER_TIMEOUT_S = 120
_REALISTIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]
_URL_RE = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
# Match bare domains like "homedepot.com", "amazon.co.uk"
_BARE_DOMAIN_RE = re.compile(
    r"\b([a-zA-Z0-9-]+\.(?:com|org|net|io|co|ru|uk|de|fr|es|it|ca|au|"
    r"co\.uk|co\.jp|com\.br|com\.au)[^\s]*)",
    re.IGNORECASE,
)
_WRITE_TASK_HINTS = (
    "fill",
    "submit",
    "order",
    "book",
    "register",
    "sign up",
    "signup",
    "buy",
    "checkout",
    "purchase",
)


class BrowserTool:
    """Executes browser tasks via Browser-Use with Playwright fallback."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._model = model

    async def execute_task(
        self,
        task: str,
        max_steps: int = 10,
        timeout: float = BROWSER_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Run a browser automation task.

        Returns dict with keys:
        - success: bool
        - result: str (extracted data or error message)
        - steps: int (how many steps were taken)
        """
        primary = await self._execute_with_browser_use(
            task=task,
            max_steps=max_steps,
            timeout=timeout,
        )
        if primary["success"]:
            return primary

        fallback = await self._execute_with_playwright(task=task, timeout=timeout)
        if fallback["success"]:
            return fallback

        return {
            "success": False,
            "result": (
                f"{primary['result']}\n"
                f"Playwright fallback failed: {fallback['result']}"
            ),
            "steps": 0,
            "engine": "none",
        }

    async def _execute_with_browser_use(
        self,
        task: str,
        max_steps: int,
        timeout: float,
    ) -> dict[str, Any]:
        """Primary path: Browser-Use agent."""
        self._ensure_browser_use_config_dir()
        try:
            from browser_use import Agent as BrowserAgent
            from browser_use import BrowserProfile
            from browser_use import ChatAnthropic as BrowserUseChatAnthropic
        except ImportError:
            return {
                "success": False,
                "result": (
                    "Browser-Use is not available. "
                    "Install the browser-use package."
                ),
                "steps": 0,
                "engine": "browser_use",
            }

        try:
            llm = BrowserUseChatAnthropic(model=self._model)
            browser_profile = BrowserProfile(
                headless=True,
                enable_default_extensions=False,
                user_agent=_REALISTIC_UA,
                args=_STEALTH_ARGS,
            )
            agent = BrowserAgent(task=task, llm=llm, browser_profile=browser_profile)
            history = await asyncio.wait_for(
                agent.run(max_steps=max_steps),
                timeout=timeout,
            )
            # Extract clean result text from AgentHistoryList
            final = history.final_result() if hasattr(history, "final_result") else None
            if not final:
                # Fallback: collect extracted_content from all action results
                parts = []
                for ar in history.all_results:
                    if ar.extracted_content:
                        parts.append(ar.extracted_content)
                final = "\n".join(parts) if parts else str(history)
            return {
                "success": bool(final),
                "result": final or "Browser-Use completed but returned no data.",
                "steps": max_steps,
                "engine": "browser_use",
            }
        except TimeoutError:
            # Try to salvage partial results from agent history
            partial = self._extract_partial_results(agent)
            if partial:
                logger.info("Browser-Use timed out but salvaged partial results")
                return {
                    "success": True,
                    "result": partial,
                    "steps": 0,
                    "engine": "browser_use",
                }
            return {
                "success": False,
                "result": f"Browser-Use task timed out after {timeout}s.",
                "steps": 0,
                "engine": "browser_use",
            }
        except Exception as e:
            logger.exception("Browser-Use task failed: %s", task[:100])
            return {
                "success": False,
                "result": f"Browser-Use failed: {e}",
                "steps": 0,
                "engine": "browser_use",
            }

    async def _execute_with_playwright(self, task: str, timeout: float) -> dict[str, Any]:
        """Fallback path: Playwright read-only extraction."""
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError:
            return {
                "success": False,
                "result": (
                    "Playwright is not available. Install playwright and run "
                    "'playwright install chromium'."
                ),
                "steps": 0,
                "engine": "playwright",
            }

        if self._is_write_task(task):
            return {
                "success": False,
                "result": (
                    "Playwright fallback supports read-only tasks only. "
                    "For form submissions/orders, Browser-Use is required."
                ),
                "steps": 0,
                "engine": "playwright",
            }

        target_url = self._extract_url(task)
        # If task has a target domain + search intent, use Google site: search
        # instead of loading the homepage (many sites block headless browsers).
        start_url = self._build_playwright_url(task, target_url)
        timeout_ms = max(int(timeout * 1000), 1_000)

        try:
            from playwright_stealth import Stealth

            async with Stealth().use_async(async_playwright()) as pw:
                browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
                context = await browser.new_context(user_agent=_REALISTIC_UA)
                page = await context.new_page()
                await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)

                title = await page.title()
                page_url = page.url

                body_text = ""
                try:
                    body_text = await page.locator("body").inner_text(timeout=5_000)
                except Exception:
                    body_text = ""

                compact_text = self._compact_text(body_text, max_chars=2_000)
                await browser.close()

            snippet = compact_text if compact_text else "No readable text extracted."
            return {
                "success": True,
                "result": (
                    f"Source: Playwright fallback\n"
                    f"Title: {title}\n"
                    f"URL: {page_url}\n"
                    f"Snippet: {snippet}"
                ),
                "steps": 1,
                "engine": "playwright",
            }
        except PlaywrightTimeoutError:
            return {
                "success": False,
                "result": f"Playwright task timed out after {timeout}s.",
                "steps": 0,
                "engine": "playwright",
            }
        except Exception as e:
            logger.exception("Playwright fallback failed: %s", task[:100])
            return {
                "success": False,
                "result": f"Playwright failed: {e}",
                "steps": 0,
                "engine": "playwright",
            }

    def _extract_url(self, task: str) -> str | None:
        """Extract first URL from task text (supports bare domains like homedepot.com)."""
        match = _URL_RE.search(task or "")
        if match:
            return match.group(0).rstrip(".,;")
        bare = _BARE_DOMAIN_RE.search(task or "")
        if bare:
            return f"https://{bare.group(1).rstrip('.,;')}"
        return None

    def _build_playwright_url(self, task: str, target_url: str | None) -> str:
        """Build the best URL for Playwright fallback.

        If we have a target domain AND extra search terms, use Google site:
        search instead of going to the homepage (avoids anti-bot blocks).
        """
        if not target_url:
            return f"https://www.google.com/search?q={quote_plus(task)}"

        # Extract the domain from target_url
        domain_match = re.match(r"https?://(?:www\.)?([^/]+)", target_url)
        if not domain_match:
            return target_url

        domain = domain_match.group(1)
        # Remove URL/domain from task to get the search query part
        query = task
        for pattern in [target_url, domain, f"www.{domain}"]:
            query = query.replace(pattern, "")
        # Clean up common instruction words
        query = re.sub(
            r"\b(go to|navigate to|open|visit|check|find|зайди на|зайти на|найди|найти"
            r"|цену?|price of|the)\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"\s+", " ", query).strip(" .,;:-")

        if query:
            # Use Google with site: operator for targeted search
            google_q = f"site:{domain} {query}"
            return f"https://www.google.com/search?q={quote_plus(google_q)}"

        # No extra query — just go to the site directly
        return target_url

    def _is_write_task(self, task: str) -> bool:
        """Detect likely side-effecting tasks.

        Strips domain names first so 'booking.com' doesn't match 'book'.
        """
        text = re.sub(r"[a-zA-Z0-9-]+\.\w{2,}", "", task or "")
        return bool(
            re.search(
                r"\b(fill|submit|order|book|register|sign\s*up|signup"
                r"|buy|checkout|purchase)\b",
                text,
                re.IGNORECASE,
            )
        )

    def _extract_partial_results(self, agent: Any) -> str | None:
        """Try to salvage extracted content from a Browser-Use agent after timeout."""
        try:
            history = getattr(agent, "_history", None) or getattr(agent, "history", None)
            if not history:
                return None
            results = getattr(history, "all_results", None)
            if not results:
                return None
            parts = []
            for ar in results:
                content = getattr(ar, "extracted_content", None)
                if content:
                    parts.append(content)
            return "\n".join(parts) if parts else None
        except Exception:
            return None

    def _compact_text(self, text: str, max_chars: int = 1_200) -> str:
        """Normalize whitespace and clamp output size."""
        if not text:
            return ""
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + "..."

    def _ensure_browser_use_config_dir(self) -> None:
        """Set a writable browser-use config dir if not provided."""
        if os.getenv("BROWSER_USE_CONFIG_DIR"):
            return
        default_dir = os.path.join(tempfile.gettempdir(), "browseruse")
        os.makedirs(default_dir, exist_ok=True)
        os.environ["BROWSER_USE_CONFIG_DIR"] = default_dir


# Module-level singleton
browser_tool = BrowserTool()
