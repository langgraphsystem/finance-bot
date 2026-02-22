"""Tests for browser automation tool."""

import os
from unittest.mock import AsyncMock, patch

from src.tools.browser import BROWSER_TIMEOUT_S, BrowserTool, browser_tool


def test_browser_tool_singleton_exists():
    assert browser_tool is not None
    assert isinstance(browser_tool, BrowserTool)


def test_browser_timeout_is_60():
    assert BROWSER_TIMEOUT_S == 60


def test_extract_url():
    tool = BrowserTool()
    assert tool._extract_url("check https://example.com/item?id=1 now") == "https://example.com/item?id=1"
    assert tool._extract_url("no url here") is None


def test_extract_url_bare_domain():
    tool = BrowserTool()
    assert tool._extract_url("go to homedepot.com and find 2x4") == "https://homedepot.com"
    assert tool._extract_url("check amazon.co.uk for deals") == "https://amazon.co.uk"


def test_build_playwright_url_no_target():
    tool = BrowserTool()
    url = tool._build_playwright_url("what is the weather today", None)
    assert "google.com/search" in url
    assert "weather+today" in url


def test_build_playwright_url_domain_with_query():
    tool = BrowserTool()
    url = tool._build_playwright_url(
        "Go to homedepot.com and find the price of 2x4 board",
        "https://homedepot.com",
    )
    assert "google.com/search" in url
    assert "site%3Ahomedepot.com" in url
    assert "2x4" in url


def test_build_playwright_url_domain_only():
    tool = BrowserTool()
    url = tool._build_playwright_url(
        "go to homedepot.com",
        "https://homedepot.com",
    )
    # No extra query after removing domain + instruction words → go directly
    assert url == "https://homedepot.com"


def test_build_playwright_url_russian_query():
    tool = BrowserTool()
    url = tool._build_playwright_url(
        "зайди на homedepot.com и найди цену на доску 2x4",
        "https://homedepot.com",
    )
    assert "google.com/search" in url
    assert "site%3Ahomedepot.com" in url


def test_is_write_task():
    tool = BrowserTool()
    assert tool._is_write_task("submit order on website") is True
    assert tool._is_write_task("check store opening hours") is False


def test_compact_text_clamps():
    tool = BrowserTool()
    text = "a " * 800
    compact = tool._compact_text(text, max_chars=100)
    assert len(compact) <= 103  # 100 + "..."
    assert compact.endswith("...")


def test_ensure_browser_use_config_dir_sets_default(tmp_path, monkeypatch):
    tool = BrowserTool()
    monkeypatch.delenv("BROWSER_USE_CONFIG_DIR", raising=False)
    with patch("src.tools.browser.tempfile.gettempdir", return_value=str(tmp_path)):
        tool._ensure_browser_use_config_dir()

    configured = os.getenv("BROWSER_USE_CONFIG_DIR")
    assert configured is not None
    assert configured.startswith(str(tmp_path))
    assert os.path.isdir(configured)


def test_ensure_browser_use_config_dir_does_not_override(monkeypatch):
    tool = BrowserTool()
    monkeypatch.setenv("BROWSER_USE_CONFIG_DIR", "D:/custom/browseruse")
    tool._ensure_browser_use_config_dir()
    assert os.getenv("BROWSER_USE_CONFIG_DIR") == "D:/custom/browseruse"


async def test_execute_task_primary_success_skips_fallback():
    tool = BrowserTool()
    with (
        patch.object(
            tool,
            "_execute_with_browser_use",
            new_callable=AsyncMock,
            return_value={"success": True, "result": "ok", "steps": 2, "engine": "browser_use"},
        ) as mock_primary,
        patch.object(
            tool,
            "_execute_with_playwright",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": "fallback",
                "steps": 1,
                "engine": "playwright",
            },
        ) as mock_fallback,
    ):
        result = await tool.execute_task("check price")

    assert result["success"] is True
    assert result["engine"] == "browser_use"
    mock_primary.assert_awaited_once()
    mock_fallback.assert_not_awaited()


async def test_execute_task_uses_playwright_fallback_when_primary_fails():
    tool = BrowserTool()
    with (
        patch.object(
            tool,
            "_execute_with_browser_use",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "result": "Browser-Use is not available.",
                "steps": 0,
                "engine": "browser_use",
            },
        ) as mock_primary,
        patch.object(
            tool,
            "_execute_with_playwright",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "result": "Source: Playwright fallback",
                "steps": 1,
                "engine": "playwright",
            },
        ) as mock_fallback,
    ):
        result = await tool.execute_task("check price")

    assert result["success"] is True
    assert result["engine"] == "playwright"
    mock_primary.assert_awaited_once()
    mock_fallback.assert_awaited_once()


async def test_execute_task_returns_combined_error_when_both_fail():
    tool = BrowserTool()
    with (
        patch.object(
            tool,
            "_execute_with_browser_use",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "result": "Browser-Use failed: boom",
                "steps": 0,
                "engine": "browser_use",
            },
        ),
        patch.object(
            tool,
            "_execute_with_playwright",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "result": "Playwright failed: boom2",
                "steps": 0,
                "engine": "playwright",
            },
        ),
    ):
        result = await tool.execute_task("check price")

    assert result["success"] is False
    assert "Browser-Use failed" in result["result"]
    assert "Playwright fallback failed" in result["result"]
    assert result["engine"] == "none"
