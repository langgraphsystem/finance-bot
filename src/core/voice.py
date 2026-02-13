"""Voice transcription via OpenAI gpt-4o-transcribe."""

import logging

from src.core.llm.clients import openai_client
from src.core.observability import observe

logger = logging.getLogger(__name__)


@observe(name="voice_transcribe")
async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe voice message using gpt-4o-transcribe with whisper-1 fallback."""
    client = openai_client()

    # Try gpt-4o-transcribe first
    try:
        transcript = await client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=(filename, audio_bytes),
            language="ru",
        )
        return transcript.text
    except Exception as e:
        logger.warning("gpt-4o-transcribe failed, falling back to whisper-1: %s", e)

    # Fallback to whisper-1
    try:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes),
            language="ru",
        )
        return transcript.text
    except Exception as e:
        logger.error("whisper-1 fallback also failed: %s", e)
        return ""
