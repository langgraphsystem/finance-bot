"""Voice pilot readiness helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.voice.config import VoiceConfig


@dataclass
class VoicePilotReadinessItem:
    """One readiness check for voice pilot launch."""

    name: str
    ok: bool
    detail: str


@dataclass
class VoicePilotReadinessReport:
    """Aggregated readiness report for voice pilot enablement."""

    ready: bool
    rollout_state: dict[str, bool]
    checks: list[VoicePilotReadinessItem] = field(default_factory=list)


def build_voice_pilot_readiness(config: VoiceConfig) -> VoicePilotReadinessReport:
    """Evaluate whether the current environment is ready for a voice pilot."""
    checks = [
        VoicePilotReadinessItem(
            name="voice_enabled",
            ok=config.enabled,
            detail=(
                "Voice runtime is enabled."
                if config.enabled
                else "Set VOICE_ENABLED=true before pilot launch."
            ),
        ),
        VoicePilotReadinessItem(
            name="public_base_url",
            ok=bool(config.public_base_url),
            detail=(
                f"Using public base URL {config.public_base_url}."
                if config.public_base_url
                else "Set VOICE_PUBLIC_BASE_URL or TELEGRAM_WEBHOOK_URL."
            ),
        ),
        VoicePilotReadinessItem(
            name="websocket_base_url",
            ok=bool(config.ws_base_url),
            detail=(
                f"Using websocket base URL {config.ws_base_url}."
                if config.ws_base_url
                else "Set VOICE_WS_BASE_URL or derive it from VOICE_PUBLIC_BASE_URL."
            ),
        ),
        VoicePilotReadinessItem(
            name="openai_realtime",
            ok=config.realtime_configured,
            detail=(
                f"Realtime model {config.openai_realtime_model} is configured."
                if config.realtime_configured
                else "Set OPENAI_API_KEY and VOICE_OPENAI_REALTIME_MODEL."
            ),
        ),
        VoicePilotReadinessItem(
            name="twilio_voice",
            ok=config.twilio_configured,
            detail=(
                "Twilio voice credentials are configured."
                if config.twilio_configured
                else "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER."
            ),
        ),
        VoicePilotReadinessItem(
            name="owner_binding",
            ok=bool(config.default_owner_telegram_id),
            detail=(
                "Default owner Telegram binding is configured."
                if config.default_owner_telegram_id
                else "Set VOICE_DEFAULT_OWNER_TELEGRAM_ID for pilot handoffs and approvals."
            ),
        ),
        VoicePilotReadinessItem(
            name="outbound_mode",
            ok=True,
            detail=(
                "Outbound pilot is enabled."
                if config.allow_outbound
                else "Outbound calls are disabled for soft launch."
            ),
        ),
        VoicePilotReadinessItem(
            name="write_tool_mode",
            ok=True,
            detail=(
                "Write tools are enabled."
                if config.allow_write_tools
                else "Write tools are disabled; pilot will run in receptionist-safe mode."
            ),
        ),
        VoicePilotReadinessItem(
            name="callback_fallback",
            ok=True,
            detail=(
                "Callback-only emergency mode is active."
                if config.force_callback_mode
                else "Callback-only emergency mode is available but not active."
            ),
        ),
    ]
    ready = all(item.ok for item in checks[:6])
    return VoicePilotReadinessReport(
        ready=ready,
        rollout_state=config.rollout_state(),
        checks=checks,
    )
