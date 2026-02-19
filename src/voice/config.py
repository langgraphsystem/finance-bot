"""Voice call configuration — Twilio + OpenAI Realtime settings."""

import os


class VoiceConfig:
    """Centralised config for voice calling subsystem."""

    # Twilio
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_voice_number: str = os.getenv("TWILIO_VOICE_NUMBER", "")

    # OpenAI Realtime
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_realtime_model: str = "gpt-4o-realtime-preview"
    openai_realtime_voice: str = "alloy"

    # WebSocket
    ws_base_url: str = os.getenv("VOICE_WS_BASE_URL", "wss://localhost:8000")

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_voice_number)


voice_config = VoiceConfig()
