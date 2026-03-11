"""Redis-backed storage for voice call review snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from src.core.db import redis


@dataclass
class VoiceCallReview:
    """Compact review snapshot used by ops and QA tooling."""

    call_id: str
    created_at: str
    call_type: str
    caller: str
    duration_seconds: int
    disposition: str
    summary_text: str
    tool_names: list[str] = field(default_factory=list)
    approvals_requested: int = 0
    auth_state: str = "unknown"
    qa_score: int = 0
    qa_status: str = "review"
    qa_flags: list[str] = field(default_factory=list)
    qa_notes: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)


class VoiceReviewStore:
    """Persist review snapshots for recent voice calls."""

    key_prefix = "voice:review:"
    recent_key = "voice:review:recent"
    ttl_seconds = 604800
    max_recent = 200

    def _key(self, call_id: str) -> str:
        return f"{self.key_prefix}{call_id}"

    async def save(self, review: VoiceCallReview) -> None:
        key = self._key(review.call_id)
        await redis.set(key, json.dumps(asdict(review)), ex=self.ttl_seconds)
        await redis.lrem(self.recent_key, 0, review.call_id)
        await redis.lpush(self.recent_key, review.call_id)
        await redis.ltrim(self.recent_key, 0, self.max_recent - 1)
        await redis.expire(self.recent_key, self.ttl_seconds)

    async def load(self, call_id: str) -> VoiceCallReview | None:
        payload = await redis.get(self._key(call_id))
        if not payload:
            return None
        return VoiceCallReview(**json.loads(payload))

    async def recent(self, limit: int = 20) -> list[VoiceCallReview]:
        call_ids = await redis.lrange(self.recent_key, 0, max(limit - 1, 0))
        reviews: list[VoiceCallReview] = []
        for call_id in call_ids:
            review = await self.load(call_id)
            if review is not None:
                reviews.append(review)
        return reviews


voice_review_store = VoiceReviewStore()
