"""Voice call configuration for Twilio and OpenAI Realtime."""

from dataclasses import dataclass

from src.core.config import settings


def _normalize_base_url(url: str) -> str:
    """Return a base URL without trailing slash."""
    return url.rstrip("/")


def _http_to_ws(url: str) -> str:
    """Convert an HTTP(S) URL to WS(S)."""
    if url.startswith("https://"):
        return "wss://" + url.removeprefix("https://")
    if url.startswith("http://"):
        return "ws://" + url.removeprefix("http://")
    return url


@dataclass
class VoiceConfig:
    """Centralised config for the voice subsystem."""

    twilio_account_sid: str = settings.twilio_account_sid
    twilio_auth_token: str = settings.twilio_auth_token
    twilio_voice_number: str = settings.twilio_phone_number
    openai_api_key: str = settings.openai_api_key
    openai_realtime_model: str = settings.voice_openai_realtime_model
    openai_realtime_fallback_model: str = settings.voice_openai_realtime_fallback_model
    openai_realtime_voice: str = settings.voice_openai_realtime_voice
    public_base_url: str = ""
    ws_base_url: str = ""
    default_owner_name: str = settings.voice_default_owner_name
    default_business_name: str = settings.voice_default_business_name
    default_business_hours: str = settings.voice_default_business_hours
    default_services: str = settings.voice_default_services

    def __post_init__(self) -> None:
        if not self.public_base_url:
            self.public_base_url = _normalize_base_url(
                settings.voice_public_base_url or settings.public_base_url
            )
        if not self.ws_base_url:
            source = settings.voice_ws_base_url or self.public_base_url
            self.ws_base_url = _normalize_base_url(_http_to_ws(source))

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_voice_number)

    @property
    def realtime_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_realtime_model)

    def build_websocket_url(self, call_type: str, call_id: str) -> str:
        """Build the public websocket URL that Twilio connects to."""
        return f"{self.ws_base_url}/ws/voice/{call_type}/{call_id}"

    def build_outbound_webhook_url(self, call_id: str) -> str:
        """Build the Twilio callback URL for outbound call instructions."""
        return f"{self.public_base_url}/webhook/voice/outbound/{call_id}"

    def build_status_callback_url(self, call_id: str | None = None) -> str:
        """Build the Twilio status callback URL."""
        url = f"{self.public_base_url}/webhook/voice/status"
        if call_id:
            return f"{url}?call_id={call_id}"
        return url


voice_config = VoiceConfig()
