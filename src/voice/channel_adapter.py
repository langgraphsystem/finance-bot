"""Helpers for binding a voice call to the same agent context as Telegram."""

from dataclasses import replace

from src.core.context import SessionContext
from src.voice.config import voice_config
from src.voice.session_store import VoiceCallMetadata


async def build_voice_context(metadata: VoiceCallMetadata) -> SessionContext | None:
    """Resolve a voice call to an existing user SessionContext."""
    owner_telegram_id = metadata.owner_telegram_id or voice_config.default_owner_telegram_id
    if not owner_telegram_id:
        return None

    from api.main import build_session_context

    context = await build_session_context(str(owner_telegram_id))
    if context is None:
        return None

    return replace(
        context,
        channel="voice",
        channel_user_id=metadata.from_phone or metadata.to_phone or metadata.call_id,
    )
