"""Tests for voice configuration."""

from src.voice.config import VoiceConfig


def test_default_config():
    config = VoiceConfig()
    assert config.openai_realtime_model == "gpt-4o-realtime-preview"
    assert config.openai_realtime_voice == "alloy"


def test_twilio_not_configured_by_default():
    config = VoiceConfig()
    # Without env vars, twilio should not be configured
    assert not config.twilio_configured


def test_twilio_configured_with_values():
    config = VoiceConfig()
    config.twilio_account_sid = "AC123"
    config.twilio_auth_token = "token"
    config.twilio_voice_number = "+1234567890"
    assert config.twilio_configured
