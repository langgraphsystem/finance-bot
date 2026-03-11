"""Tests for voice pilot readiness checks."""

from src.voice.config import VoiceConfig
from src.voice.pilot import build_voice_pilot_readiness


def test_voice_pilot_readiness_is_false_without_required_config():
    report = build_voice_pilot_readiness(
        VoiceConfig(
            enabled=False,
            public_base_url="",
            ws_base_url="",
            openai_api_key="",
            openai_realtime_model="",
            twilio_account_sid="",
            twilio_auth_token="",
            twilio_voice_number="",
            default_owner_telegram_id="",
        )
    )

    assert report.ready is False
    failed = {item.name for item in report.checks if not item.ok}
    assert "voice_enabled" in failed
    assert "openai_realtime" in failed
    assert "twilio_voice" in failed


def test_voice_pilot_readiness_is_true_with_required_config():
    report = build_voice_pilot_readiness(
        VoiceConfig(
            enabled=True,
            public_base_url="https://example.com",
            ws_base_url="wss://example.com",
            openai_api_key="sk-test",
            openai_realtime_model="gpt-realtime-1.5",
            twilio_account_sid="AC123",
            twilio_auth_token="token",
            twilio_voice_number="+15551234567",
            default_owner_telegram_id="123456",
        )
    )

    assert report.ready is True
    assert report.rollout_state["enabled"] is True
