"""Video session — stores analyzed video context in Redis for follow-up actions."""

import json
import logging
from dataclasses import asdict, dataclass, field

from src.core.db import redis

logger = logging.getLogger(__name__)

VIDEO_SESSION_TTL = 1800  # 30 minutes


@dataclass
class VideoSession:
    url: str
    platform: str  # "youtube" | "tiktok"
    title: str = ""
    transcript: str = ""  # raw transcript text (from STT or Gemini)
    analysis: str = ""    # initial Gemini analysis shown to user
    language: str = "en"
    extra: dict = field(default_factory=dict)  # platform-specific metadata


async def save_video_session(user_id: str, session: VideoSession) -> None:
    key = f"video_session:{user_id}"
    await redis.set(key, json.dumps(asdict(session)), ex=VIDEO_SESSION_TTL)


async def get_video_session(user_id: str) -> VideoSession | None:
    key = f"video_session:{user_id}"
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return VideoSession(**data)
    except Exception as e:
        logger.warning("Failed to parse video session for %s: %s", user_id, e)
        return None


async def clear_video_session(user_id: str) -> None:
    await redis.delete(f"video_session:{user_id}")
