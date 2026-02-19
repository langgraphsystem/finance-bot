"""Tests for youtube_search skill — quick (grounding) + detailed (API) modes."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.youtube_search.handler import (
    YouTubeSearchSkill,
    _html_fallback,
    extract_youtube_url,
)


@pytest.fixture
def skill():
    return YouTubeSearchSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="how to change oil in Toyota Camry",
    )


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


# ---------------------------------------------------------------------------
# Quick mode (Gemini Google Search Grounding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_mode_default(skill, message, ctx):
    """Default (no detail_mode, no API key) uses Gemini grounding."""
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube_grounding",
            new_callable=AsyncMock,
            return_value="<b>How to Change Oil</b>\n1. Drain old oil",
        ) as mock_grounding,
    ):
        mock_settings.youtube_api_key = ""
        result = await skill.execute(message, ctx, {"youtube_query": "oil change Toyota Camry"})

    mock_grounding.assert_awaited_once_with("oil change Toyota Camry", "en")
    assert "oil" in result.response_text.lower()


@pytest.mark.asyncio
async def test_quick_mode_with_api_key_no_detail(skill, message, ctx):
    """Even with API key, no detail_mode means grounding mode."""
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube_grounding",
            new_callable=AsyncMock,
            return_value="<b>Oil Tutorial</b>",
        ) as mock_grounding,
    ):
        mock_settings.youtube_api_key = "fake-key"
        await skill.execute(message, ctx, {"youtube_query": "oil change"})

    mock_grounding.assert_awaited_once()


@pytest.mark.asyncio
async def test_grounding_calls_gemini_with_google_search_tool(skill, ctx):
    """search_youtube_grounding calls Gemini with GoogleSearch tool."""
    mock_response = MagicMock()
    mock_response.text = "<b>Toyota Camry Oil Change</b> — ChrisFix"

    mock_generate = AsyncMock(return_value=mock_response)

    with patch("src.skills.youtube_search.handler.google_client") as mock_gc:
        mock_gc.return_value.aio.models.generate_content = mock_generate
        from src.skills.youtube_search.handler import search_youtube_grounding

        result = await search_youtube_grounding("oil change Toyota", "en")

    assert "Toyota" in result
    call_kwargs = mock_generate.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config is not None
    assert len(config.tools) == 1


# ---------------------------------------------------------------------------
# Detailed mode (YouTube Data API v3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_mode_uses_api(skill, message, ctx):
    """detail_mode=True + API key → uses search_youtube (REST API)."""
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube",
            new_callable=AsyncMock,
            return_value="<b>How to Change Oil</b>\n1. Drain old oil\n2. Replace filter",
        ) as mock_api,
    ):
        mock_settings.youtube_api_key = "fake-key"
        result = await skill.execute(
            message, ctx, {"youtube_query": "oil change Toyota Camry", "detail_mode": True}
        )

    mock_api.assert_awaited_once_with("oil change Toyota Camry", "en")
    assert "oil" in result.response_text.lower()


@pytest.mark.asyncio
async def test_detail_mode_no_api_key_falls_to_grounding(skill, message, ctx):
    """detail_mode=True without API key gracefully falls to grounding."""
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube_grounding",
            new_callable=AsyncMock,
            return_value="<b>Oil Change Video</b>",
        ) as mock_grounding,
    ):
        mock_settings.youtube_api_key = ""
        await skill.execute(message, ctx, {"youtube_query": "oil change", "detail_mode": True})

    mock_grounding.assert_awaited_once()


# ---------------------------------------------------------------------------
# YouTube URL analysis
# ---------------------------------------------------------------------------


def test_extract_youtube_url_watch():
    assert extract_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is not None


def test_extract_youtube_url_short():
    assert extract_youtube_url("https://youtu.be/dQw4w9WgXcQ") is not None


def test_extract_youtube_url_shorts():
    assert extract_youtube_url("https://youtube.com/shorts/abc123") is not None


def test_extract_youtube_url_mobile():
    assert extract_youtube_url("https://m.youtube.com/watch?v=abc123") is not None


def test_extract_youtube_url_none_for_plain_text():
    assert extract_youtube_url("how to change oil Toyota Camry") is None


def test_extract_youtube_url_embedded_in_text():
    url = extract_youtube_url("check this out https://youtu.be/abc123 cool right?")
    assert url == "https://youtu.be/abc123"


@pytest.mark.asyncio
async def test_url_routes_to_analyze(skill, ctx):
    """When query contains a YouTube URL, it routes to analyze_youtube_url."""
    msg = IncomingMessage(
        id="msg-url-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    with patch(
        "src.skills.youtube_search.handler.analyze_youtube_url",
        new_callable=AsyncMock,
        return_value="<b>Never Gonna Give You Up</b> — Rick Astley",
    ) as mock_analyze:
        result = await skill.execute(
            msg, ctx, {"youtube_query": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        )

    mock_analyze.assert_awaited_once()
    assert "Rick Astley" in result.response_text


@pytest.mark.asyncio
async def test_url_with_comment_routes_to_analyze(skill, ctx):
    """URL + user comment both get passed to analyze."""
    msg = IncomingMessage(
        id="msg-url-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what is this? https://youtu.be/abc123",
    )
    with patch(
        "src.skills.youtube_search.handler.analyze_youtube_url",
        new_callable=AsyncMock,
        return_value="<b>Video Analysis</b>",
    ) as mock_analyze:
        result = await skill.execute(
            msg, ctx, {"youtube_query": "what is this? https://youtu.be/abc123"}
        )

    mock_analyze.assert_awaited_once_with(
        "https://youtu.be/abc123",
        "what is this? https://youtu.be/abc123",
        "en",
    )
    assert "Video Analysis" in result.response_text


@pytest.mark.asyncio
async def test_analyze_youtube_url_calls_gemini_with_grounding():
    """analyze_youtube_url uses Gemini with Google Search grounding."""
    mock_response = MagicMock()
    mock_response.text = "<b>Oil Change Tutorial</b> by ChrisFix — step by step guide"

    mock_generate = AsyncMock(return_value=mock_response)

    with patch("src.skills.youtube_search.handler.google_client") as mock_gc:
        mock_gc.return_value.aio.models.generate_content = mock_generate
        from src.skills.youtube_search.handler import analyze_youtube_url

        result = await analyze_youtube_url(
            "https://youtube.com/watch?v=abc123", "https://youtube.com/watch?v=abc123", "en"
        )

    assert "Oil Change Tutorial" in result
    call_kwargs = mock_generate.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config is not None
    assert len(config.tools) == 1


@pytest.mark.asyncio
async def test_analyze_youtube_url_failure_returns_link():
    """When Gemini fails, return a fallback with the URL."""
    mock_generate = AsyncMock(side_effect=Exception("API error"))

    with patch("src.skills.youtube_search.handler.google_client") as mock_gc:
        mock_gc.return_value.aio.models.generate_content = mock_generate
        from src.skills.youtube_search.handler import analyze_youtube_url

        result = await analyze_youtube_url(
            "https://youtube.com/watch?v=xyz", "https://youtube.com/watch?v=xyz", "en"
        )

    assert "https://youtube.com/watch?v=xyz" in result
    assert "Could not analyze" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "YouTube" in result.response_text


@pytest.mark.asyncio
async def test_uses_message_text_as_fallback(skill, ctx):
    """Falls back to message.text when no youtube_query in intent_data."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="iPhone 16 review youtube",
    )
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube_grounding",
            new_callable=AsyncMock,
            return_value="<b>iPhone 16 Review</b>",
        ) as mock_grounding,
    ):
        mock_settings.youtube_api_key = ""
        result = await skill.execute(msg, ctx, {})

    mock_grounding.assert_awaited_once_with("iPhone 16 review youtube", "en")
    assert "iPhone" in result.response_text


@pytest.mark.asyncio
async def test_api_error_returns_message(skill, ctx):
    """Returns error message when YouTube API fails."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="how to fix car",
    )
    with (
        patch("src.skills.youtube_search.handler.settings") as mock_settings,
        patch(
            "src.skills.youtube_search.handler.search_youtube",
            new_callable=AsyncMock,
            return_value="Could not reach YouTube. Try again later.",
        ),
    ):
        mock_settings.youtube_api_key = "fake-key"
        result = await skill.execute(
            msg, ctx, {"youtube_query": "how to fix car", "detail_mode": True}
        )

    assert "YouTube" in result.response_text


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_html_fallback_includes_links():
    """_html_fallback formats videos with title and URL."""
    videos = [
        {
            "title": "Oil Change Tutorial",
            "channel": "AutoFix",
            "url": "https://youtube.com/watch?v=abc123",
        }
    ]
    result = _html_fallback(videos)
    assert "Oil Change Tutorial" in result
    assert "https://youtube.com/watch?v=abc123" in result
    assert "AutoFix" in result


def test_system_prompt_includes_language(skill, ctx):
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
