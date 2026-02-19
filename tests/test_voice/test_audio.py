"""Tests for audio transcoding utilities."""

import base64

from src.voice.audio import mulaw_to_pcm16, pcm16_to_mulaw


def test_mulaw_to_pcm16_returns_base64():
    """mu-law to PCM16 conversion should return valid base64."""
    # Create a small mu-law audio sample (silence = 0xFF in mu-law)
    mulaw_data = bytes([0xFF] * 160)  # 20ms at 8kHz
    mulaw_b64 = base64.b64encode(mulaw_data).decode("ascii")

    result = mulaw_to_pcm16(mulaw_b64)

    # Should be valid base64
    decoded = base64.b64decode(result)
    assert len(decoded) > 0
    # PCM16 at 16kHz should be ~4x size of mu-law at 8kHz
    # (2 bytes per sample * 2x sample rate)
    assert len(decoded) > len(mulaw_data)


def test_pcm16_to_mulaw_returns_base64():
    """PCM16 to mu-law conversion should return valid base64."""
    # Create a small PCM16 audio sample (silence = 0x00)
    pcm_data = bytes([0x00] * 640)  # 20ms at 16kHz, 2 bytes/sample
    pcm_b64 = base64.b64encode(pcm_data).decode("ascii")

    result = pcm16_to_mulaw(pcm_b64)

    decoded = base64.b64decode(result)
    assert len(decoded) > 0
    # mu-law at 8kHz should be smaller than PCM16 at 16kHz
    assert len(decoded) < len(pcm_data)


def test_roundtrip_preserves_length():
    """Converting mu-law -> PCM16 -> mu-law should produce same length output."""
    mulaw_data = bytes([0x80] * 160)
    mulaw_b64 = base64.b64encode(mulaw_data).decode("ascii")

    pcm_b64 = mulaw_to_pcm16(mulaw_b64)
    result_b64 = pcm16_to_mulaw(pcm_b64)

    result = base64.b64decode(result_b64)
    assert len(result) == len(mulaw_data)
