"""Redis-backed trace recording for voice calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from src.core.db import redis


@dataclass
class VoiceTraceEvent:
    """Single trace event for a voice call."""

    timestamp: str
    kind: str
    payload: dict[str, Any]


class VoiceTraceStore:
    """Append-only trace store for active voice calls."""

    key_prefix = "voice:trace:"
    ttl_seconds = 86400

    def _key(self, call_id: str) -> str:
        return f"{self.key_prefix}{call_id}"

    async def append(self, call_id: str, kind: str, payload: dict[str, Any]) -> None:
        event = VoiceTraceEvent(
            timestamp=datetime.now(UTC).isoformat(),
            kind=kind,
            payload=payload,
        )
        key = self._key(call_id)
        await redis.rpush(key, json.dumps(asdict(event), default=str))
        await redis.expire(key, self.ttl_seconds)

    async def load(self, call_id: str) -> list[VoiceTraceEvent]:
        key = self._key(call_id)
        rows = await redis.lrange(key, 0, -1)
        return [VoiceTraceEvent(**json.loads(row)) for row in rows]


voice_trace_store = VoiceTraceStore()
