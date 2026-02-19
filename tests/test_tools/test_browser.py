"""Tests for browser automation tool."""

from unittest.mock import AsyncMock, patch

from src.tools.browser import BROWSER_TIMEOUT_S, BrowserTool, browser_tool


def test_browser_tool_singleton_exists():
    assert browser_tool is not None
    assert isinstance(browser_tool, BrowserTool)


def test_browser_timeout_is_60():
    assert BROWSER_TIMEOUT_S == 60


async def test_browser_tool_graceful_degradation():
    """When browser-use is not installed, return a clear error."""
    with patch(
        "src.tools.browser.BrowserTool.execute_task",
        new_callable=AsyncMock,
        return_value={
            "success": False,
            "result": "Browser automation is not available. "
            "Install browser-use and langchain-anthropic packages.",
            "steps": 0,
        },
    ) as mock:
        result = await mock("check price")
    assert result["success"] is False
    assert "not available" in result["result"]


async def test_browser_tool_success():
    tool = BrowserTool()
    with patch.object(
        tool,
        "execute_task",
        new_callable=AsyncMock,
        return_value={"success": True, "result": "Price: $5.99", "steps": 3},
    ):
        result = await tool.execute_task("check lumber price")
    assert result["success"] is True
    assert "$5.99" in result["result"]


async def test_browser_tool_timeout():
    tool = BrowserTool()
    with patch.object(
        tool,
        "execute_task",
        new_callable=AsyncMock,
        return_value={
            "success": False,
            "result": "Browser task timed out after 60s.",
            "steps": 0,
        },
    ):
        result = await tool.execute_task("slow task", timeout=1)
    assert result["success"] is False
    assert "timed out" in result["result"]
