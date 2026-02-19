"""Audio transcoding utilities for Twilio <-> OpenAI Realtime.

Twilio sends mu-law 8kHz audio; OpenAI Realtime expects PCM16 16kHz.
"""

import audioop
import base64


def mulaw_to_pcm16(mulaw_b64: str) -> str:
    """Convert mu-law 8kHz base64 audio to PCM16 16kHz base64.

    Steps:
    1. Decode base64 mu-law
    2. Convert mu-law -> linear PCM16 at 8kHz
    3. Upsample 8kHz -> 16kHz
    4. Encode to base64
    """
    mulaw_bytes = base64.b64decode(mulaw_b64)
    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
    pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
    return base64.b64encode(pcm_16k).decode("ascii")


def pcm16_to_mulaw(pcm16_b64: str) -> str:
    """Convert PCM16 16kHz base64 audio to mu-law 8kHz base64.

    Steps:
    1. Decode base64 PCM16
    2. Downsample 16kHz -> 8kHz
    3. Convert linear PCM16 -> mu-law
    4. Encode to base64
    """
    pcm_bytes = base64.b64decode(pcm16_b64)
    pcm_8k, _ = audioop.ratecv(pcm_bytes, 2, 1, 16000, 8000, None)
    mulaw_bytes = audioop.lin2ulaw(pcm_8k, 2)
    return base64.b64encode(mulaw_bytes).decode("ascii")
