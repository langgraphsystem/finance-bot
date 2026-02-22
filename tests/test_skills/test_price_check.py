"""Tests for price_check skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.price_check.handler import PriceCheckSkill


def test_price_check_skill_attributes():
    skill = PriceCheckSkill()
    assert skill.name == "price_check"
    assert "price_check" in skill.intents
    assert skill.model == "gemini-3-flash-preview"


def test_price_check_system_prompt(sample_context):
    skill = PriceCheckSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "price" in prompt.lower()


async def test_price_check_empty_message(sample_context):
    skill = PriceCheckSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    result = await skill.execute(msg, sample_context, {})
    assert "price" in result.response_text.lower()


async def test_grounding_success_skips_browser(sample_context):
    """When Gemini Grounding finds the price, Browser-Use is not called."""
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="2x4 lumber at Home Depot",
    )
    mock_response = MagicMock()
    mock_response.text = "<b>2x4 Lumber</b> — $3.98/piece at Home Depot"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.skills.price_check.handler.google_client", return_value=mock_client),
        patch("src.skills.price_check.handler.browser_tool") as mock_browser,
    ):
        mock_browser.execute_task = AsyncMock()
        result = await skill.execute(msg, sample_context, {})

    assert "$3.98" in result.response_text
    mock_browser.execute_task.assert_not_awaited()


async def test_grounding_empty_falls_back_to_browser(sample_context):
    """When Grounding returns empty, Browser-Use is called."""
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="obscure product XYZ",
    )
    mock_response = MagicMock()
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.skills.price_check.handler.google_client", return_value=mock_client),
        patch("src.skills.price_check.handler.browser_tool") as mock_browser,
    ):
        mock_browser.execute_task = AsyncMock(
            return_value={"success": True, "result": "$9.99 found", "steps": 3, "engine": "browser_use"}
        )
        result = await skill.execute(msg, sample_context, {})

    assert "$9.99" in result.response_text
    mock_browser.execute_task.assert_awaited_once()


async def test_grounding_exception_falls_back_to_browser(sample_context):
    """When Grounding throws an exception, Browser-Use is called."""
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="iPhone 16 Pro price",
    )
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("API down"))

    with (
        patch("src.skills.price_check.handler.google_client", return_value=mock_client),
        patch("src.skills.price_check.handler.browser_tool") as mock_browser,
    ):
        mock_browser.execute_task = AsyncMock(
            return_value={"success": True, "result": "$1199 at Apple", "steps": 5, "engine": "browser_use"}
        )
        result = await skill.execute(msg, sample_context, {})

    assert "$1199" in result.response_text


async def test_both_fail_returns_fallback_message(sample_context):
    """When both Grounding and Browser-Use fail, show fallback message."""
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="some rare product",
    )
    mock_response = MagicMock()
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.skills.price_check.handler.google_client", return_value=mock_client),
        patch("src.skills.price_check.handler.browser_tool") as mock_browser,
    ):
        mock_browser.execute_task = AsyncMock(
            return_value={"success": False, "result": "timeout", "steps": 0, "engine": "none"}
        )
        result = await skill.execute(msg, sample_context, {})

    assert "couldn't" in result.response_text.lower() or "search" in result.response_text.lower()


async def test_playwright_result_formatted_through_llm(sample_context):
    """Playwright raw output is processed through Gemini Flash."""
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1",
        type=MessageType.text, text="drill price at lowes.com",
    )
    mock_response = MagicMock()
    mock_response.text = ""  # Grounding returns nothing

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch("src.skills.price_check.handler.google_client", return_value=mock_client),
        patch("src.skills.price_check.handler.browser_tool") as mock_browser,
        patch("src.skills.price_check.handler.generate_text", new_callable=AsyncMock) as mock_gen,
    ):
        mock_browser.execute_task = AsyncMock(
            return_value={
                "success": True,
                "result": "Source: Playwright\nTitle: Lowes\nSnippet: Drill $49.99",
                "steps": 1,
                "engine": "playwright",
            }
        )
        mock_gen.return_value = "<b>Drill</b> — $49.99 at Lowes"
        result = await skill.execute(msg, sample_context, {})

    assert "$49.99" in result.response_text
    mock_gen.assert_awaited_once()
