"""Redis-backed storage for active voice call metadata."""

import json
from dataclasses import asdict, dataclass

from src.core.db import redis


@dataclass
class VoiceCallMetadata:
    """Metadata required to bootstrap a voice call session."""

    call_id: str
    call_type: str
    owner_name: str
    business_name: str
    services: str
    hours: str
    owner_telegram_id: str = ""
    from_phone: str = ""
    to_phone: str = ""
    call_sid: str = ""
    contact_name: str = ""
    call_purpose: str = ""
    call_purpose_short: str = ""
    family_id: str = ""
    status: str = "created"


class VoiceSessionStore:
    """Persist active voice session metadata in Redis."""

    key_prefix = "voice:call:"
    ttl_seconds = 86400

    def _key(self, call_id: str) -> str:
        return f"{self.key_prefix}{call_id}"

    async def save(self, metadata: VoiceCallMetadata) -> None:
        await redis.set(
            self._key(metadata.call_id),
            json.dumps(asdict(metadata)),
            ex=self.ttl_seconds,
        )

    async def get(self, call_id: str) -> VoiceCallMetadata | None:
        payload = await redis.get(self._key(call_id))
        if not payload:
            return None
        return VoiceCallMetadata(**json.loads(payload))

    async def update_status(self, call_id: str, status: str) -> None:
        metadata = await self.get(call_id)
        if not metadata:
            return
        metadata.status = status
        await self.save(metadata)


voice_session_store = VoiceSessionStore()
