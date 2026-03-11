"""Tests for voice configuration."""

from src.voice.config import VoiceConfig


def test_default_config_uses_ga_realtime_defaults():
    config = VoiceConfig()
    assert config.openai_realtime_model == "gpt-realtime-1.5"
    assert config.openai_realtime_fallback_model == "gpt-realtime-mini"
    assert config.openai_realtime_voice == "marin"


def test_ws_base_url_is_derived_from_public_base_url():
    config = VoiceConfig(public_base_url="https://example.com")
    assert config.ws_base_url == "wss://example.com"
    assert config.build_websocket_url("inbound", "call-123") == "wss://example.com/ws/voice/inbound/call-123"


def test_twilio_not_configured_by_default():
    config = VoiceConfig()
    assert not config.twilio_configured


def test_twilio_configured_with_values():
    config = VoiceConfig(
        twilio_account_sid="AC123",
        twilio_auth_token="token",
        twilio_voice_number="+1234567890",
    )
    assert config.twilio_configured


def test_rollout_state_exposes_switches():
    config = VoiceConfig(
        enabled=False,
        allow_outbound=False,
        allow_write_tools=False,
        receptionist_only=True,
        force_callback_mode=True,
    )

    assert config.rollout_state() == {
        "enabled": False,
        "allow_outbound": False,
        "allow_write_tools": False,
        "receptionist_only": True,
        "force_callback_mode": True,
    }
