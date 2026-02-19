"""AI browser automation using Browser-Use library.

Browser-Use provides an AI agent that can interact with web pages:
navigate, click, type, extract data. We wrap it with timeout and
error handling for production use.

NOTE: browser-use and langchain-anthropic are optional dependencies.
If not installed, the tool gracefully degrades with a clear error message.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

BROWSER_TIMEOUT_S = 60


class BrowserTool:
    """Executes browser tasks via Browser-Use + Claude Sonnet 4.6."""

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
        try:
            from browser_use import Agent as BrowserAgent
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            return {
                "success": False,
                "result": (
                    "Browser automation is not available. "
                    "Install browser-use and langchain-anthropic packages."
                ),
                "steps": 0,
            }

        try:
            llm = ChatAnthropic(model=self._model)
            agent = BrowserAgent(task=task, llm=llm)
            result = await asyncio.wait_for(
                agent.run(max_steps=max_steps),
                timeout=timeout,
            )
            return {
                "success": True,
                "result": str(result),
                "steps": max_steps,
            }
        except TimeoutError:
            return {
                "success": False,
                "result": f"Browser task timed out after {timeout}s.",
                "steps": 0,
            }
        except Exception as e:
            logger.exception("Browser task failed: %s", task[:100])
            return {
                "success": False,
                "result": f"Browser task failed: {e}",
                "steps": 0,
            }


# Module-level singleton
browser_tool = BrowserTool()
