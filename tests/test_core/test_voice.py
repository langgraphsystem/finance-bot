"""Tests for voice transcription."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.voice import transcribe_voice


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI async client."""
    client = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_transcribe_voice_success(mock_openai_client):
    """Test successful transcription with gpt-4o-mini-transcribe."""
    transcript_response = MagicMock()
    transcript_response.text = "Потратил 500 рублей на продукты"
    mock_openai_client.audio.transcriptions.create = AsyncMock(return_value=transcript_response)

    with patch("src.core.voice.openai_client", return_value=mock_openai_client):
        result = await transcribe_voice(b"fake_audio_bytes")

    assert result == "Потратил 500 рублей на продукты"
    mock_openai_client.audio.transcriptions.create.assert_awaited_once_with(
        model="gpt-4o-mini-transcribe",
        file=("voice.ogg", b"fake_audio_bytes"),
        language="ru",
    )


@pytest.mark.asyncio
async def test_transcribe_voice_fallback_to_whisper(mock_openai_client):
    """Test fallback to whisper-1 when gpt-4o-mini-transcribe fails."""
    transcript_response = MagicMock()
    transcript_response.text = "Записать расход 200 рублей"

    # First call (gpt-4o-mini-transcribe) fails, second call (whisper-1) succeeds
    mock_openai_client.audio.transcriptions.create = AsyncMock(
        side_effect=[
            Exception("Model unavailable"),
            transcript_response,
        ]
    )

    with patch("src.core.voice.openai_client", return_value=mock_openai_client):
        result = await transcribe_voice(b"fake_audio_bytes")

    assert result == "Записать расход 200 рублей"
    assert mock_openai_client.audio.transcriptions.create.await_count == 2

    # Verify second call used whisper-1
    second_call = mock_openai_client.audio.transcriptions.create.call_args_list[1]
    assert second_call.kwargs["model"] == "whisper-1"


@pytest.mark.asyncio
async def test_transcribe_voice_both_models_fail(mock_openai_client):
    """Test that empty string is returned when both models fail."""
    mock_openai_client.audio.transcriptions.create = AsyncMock(side_effect=Exception("API error"))

    with patch("src.core.voice.openai_client", return_value=mock_openai_client):
        result = await transcribe_voice(b"fake_audio_bytes")

    assert result == ""
    assert mock_openai_client.audio.transcriptions.create.await_count == 2


@pytest.mark.asyncio
async def test_transcribe_voice_custom_filename(mock_openai_client):
    """Test transcription with a custom filename."""
    transcript_response = MagicMock()
    transcript_response.text = "Привет"
    mock_openai_client.audio.transcriptions.create = AsyncMock(return_value=transcript_response)

    with patch("src.core.voice.openai_client", return_value=mock_openai_client):
        result = await transcribe_voice(b"fake_audio_bytes", filename="custom.ogg")

    assert result == "Привет"
    mock_openai_client.audio.transcriptions.create.assert_awaited_once_with(
        model="gpt-4o-mini-transcribe",
        file=("custom.ogg", b"fake_audio_bytes"),
        language="ru",
    )
