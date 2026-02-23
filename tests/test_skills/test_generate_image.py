"""Tests for generate_image skill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_image.handler import GenerateImageSkill


def test_generate_image_skill_attributes():
    skill = GenerateImageSkill()
    assert skill.name == "generate_image"
    assert "generate_image" in skill.intents
    assert skill.model == "gemini-3-pro-image-preview"


def test_generate_image_system_prompt(sample_context):
    skill = GenerateImageSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "image" in prompt.lower()


async def test_generate_image_empty_prompt(sample_context):
    skill = GenerateImageSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    result = await skill.execute(msg, sample_context, {})
    assert "describe" in result.response_text.lower()


async def test_generate_image_success(sample_context):
    """Primary model succeeds — return image bytes."""
    skill = GenerateImageSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="cat in space",
    )

    fake_image = b"\x89PNG_FAKE_IMAGE_DATA"

    mock_part = MagicMock()
    mock_part.inline_data = MagicMock()
    mock_part.inline_data.data = fake_image

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch(
        "src.skills.generate_image.handler.google_client",
        return_value=mock_client,
    ):
        result = await skill.execute(msg, sample_context, {"image_prompt": "cat in space"})

    assert result.photo_bytes == fake_image
    assert result.response_text == ""
    mock_client.aio.models.generate_content.assert_called_once()
    call_kwargs = mock_client.aio.models.generate_content.call_args
    assert call_kwargs[1]["model"] == "gemini-3-pro-image-preview"


async def test_generate_image_primary_fails_fallback_succeeds(sample_context):
    """Primary model fails, fallback model succeeds."""
    skill = GenerateImageSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="sunset over mountains",
    )

    fake_image = b"\x89PNG_FALLBACK_IMAGE"

    mock_part = MagicMock()
    mock_part.inline_data = MagicMock()
    mock_part.inline_data.data = fake_image

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]

    mock_response_ok = MagicMock()
    mock_response_ok.candidates = [mock_candidate]

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Pro model unavailable")
        return mock_response_ok

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=side_effect)

    with patch(
        "src.skills.generate_image.handler.google_client",
        return_value=mock_client,
    ):
        result = await skill.execute(msg, sample_context, {})

    assert result.photo_bytes == fake_image
    assert call_count == 2


async def test_generate_image_both_fail(sample_context):
    """Both models fail — return error message."""
    skill = GenerateImageSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="something",
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("API down")
    )

    with patch(
        "src.skills.generate_image.handler.google_client",
        return_value=mock_client,
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "failed" in result.response_text.lower()
    assert result.photo_bytes is None


async def test_generate_image_no_image_in_response(sample_context):
    """API returns text only (no image) — try fallback then error."""
    skill = GenerateImageSkill()
    msg = IncomingMessage(
        id="1", user_id="u1", chat_id="c1", type=MessageType.text,
        text="abstract art",
    )

    # Response with text part only, no inline_data
    mock_text_part = MagicMock()
    mock_text_part.inline_data = None

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_text_part]

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch(
        "src.skills.generate_image.handler.google_client",
        return_value=mock_client,
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "failed" in result.response_text.lower()
    # Called both models
    assert mock_client.aio.models.generate_content.call_count == 2
