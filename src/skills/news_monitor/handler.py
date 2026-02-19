"""News monitor skill — create persistent news/topic monitors.

Users say "monitor plumbing industry news" or "alert me about school closings"
and the bot creates a Monitor record checked by the proactivity engine.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import MonitorType
from src.core.models.monitor import Monitor
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You help users set up news monitoring alerts.
Confirm the topic and frequency. Be concise.
Respond in: {language}."""


class NewsMonitorSkill:
    name = "news_monitor"
    intents = ["news_monitor"]
    model = "claude-haiku-4-5"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="news_monitor")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        topic = message.text or ""
        if not topic:
            return SkillResult(
                response_text="What topic would you like me to monitor? "
                "Example: 'Monitor plumbing industry news' or 'Alert me about school closings'"
            )

        # Create monitor record
        monitor = Monitor(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            type=MonitorType.news,
            name=f"News: {topic[:100]}",
            config={"topic": topic, "keywords": topic.lower().split()[:10]},
            check_interval_minutes=720,  # twice daily
            is_active=True,
        )

        async with async_session() as session:
            session.add(monitor)
            await session.commit()

        return SkillResult(
            response_text=(
                f"Done — I'll monitor news about <b>{topic}</b> "
                f"and alert you when something relevant comes up."
            )
        )


skill = NewsMonitorSkill()
