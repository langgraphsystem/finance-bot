"""Call-scoped SMS verification for voice sessions."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass

from src.core.config import settings
from src.core.db import redis


@dataclass
class VoiceVerificationChallenge:
    """One-time verification code bound to a voice call."""

    call_id: str
    phone_number: str
    code: str
    attempts_remaining: int = 3


class VoiceVerificationStore:
    """Persist voice verification challenges in Redis."""

    key_prefix = "voice:verification:"

    def __init__(self) -> None:
        self.ttl_seconds = settings.voice_verification_ttl_seconds
        self.code_length = settings.voice_verification_code_length

    def _key(self, call_id: str) -> str:
        return f"{self.key_prefix}{call_id}"

    def _generate_code(self) -> str:
        digits = "0123456789"
        return "".join(secrets.choice(digits) for _ in range(self.code_length))

    async def create(self, call_id: str, phone_number: str) -> VoiceVerificationChallenge:
        challenge = VoiceVerificationChallenge(
            call_id=call_id,
            phone_number=phone_number,
            code=self._generate_code(),
        )
        await redis.set(self._key(call_id), json.dumps(asdict(challenge)), ex=self.ttl_seconds)
        return challenge

    async def load(self, call_id: str) -> VoiceVerificationChallenge | None:
        payload = await redis.get(self._key(call_id))
        if not payload:
            return None
        return VoiceVerificationChallenge(**json.loads(payload))

    async def verify(self, call_id: str, code: str) -> bool:
        challenge = await self.load(call_id)
        if challenge is None:
            return False

        if challenge.code == code:
            await redis.delete(self._key(call_id))
            return True

        challenge.attempts_remaining -= 1
        if challenge.attempts_remaining <= 0:
            await redis.delete(self._key(call_id))
            return False

        await redis.set(self._key(call_id), json.dumps(asdict(challenge)), ex=self.ttl_seconds)
        return False


voice_verification_store = VoiceVerificationStore()
