"""Price alert skill — create persistent price monitors.

Users say "alert me when lumber drops below $5 at Home Depot" and the bot
creates a Monitor record. The proactivity engine checks it periodically.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.enums import MonitorType
from src.core.models.monitor import Monitor
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You help users set up price monitoring alerts.
Extract: product name, target price, store/website.
Confirm what you'll monitor. Be concise.
Respond in: {language}."""

EXTRACT_PROMPT = """\
Extract monitor details from the user message. Return JSON:
{{"product": "...", "target_price": 0.00, "store": "...", "direction": "below"}}
direction is "below" (alert when price drops below target) or
"above" (alert when price rises above).
User message: {message}"""


class PriceAlertSkill:
    name = "price_alert"
    intents = ["price_alert"]
    model = "gpt-5.2"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="price_alert")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = message.text or ""
        if not text:
            return SkillResult(
                response_text="What price would you like me to monitor? "
                "Example: 'Alert me when 2x4 lumber drops below $5 at Home Depot'"
            )

        # Extract monitor details via LLM
        try:
            import json

            raw = await generate_text(
                self.model,
                "Extract price monitor details. Return only valid JSON.",
                [{"role": "user", "content": EXTRACT_PROMPT.format(message=text)}],
                max_tokens=200,
            )
            details = json.loads(raw)
        except Exception:
            logger.exception("Failed to extract monitor details")
            return SkillResult(
                response_text=(
                    "I couldn't parse that. Try: 'Monitor lumber at Home Depot, alert below $5'"
                )
            )

        product = details.get("product", "Unknown product")
        target = details.get("target_price", 0)
        store = details.get("store", "")
        direction = details.get("direction", "below")

        # Create monitor record
        monitor = Monitor(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            type=MonitorType.price,
            name=f"{product} at {store}",
            config={
                "product": product,
                "target_price": target,
                "store": store,
                "direction": direction,
            },
            check_interval_minutes=1440,  # daily
            is_active=True,
        )

        async with async_session() as session:
            session.add(monitor)
            await session.commit()

        return SkillResult(
            response_text=(
                f"Done — I'll check <b>{product}</b> at {store} daily "
                f"and alert you when the price goes {direction} ${target:.2f}."
            )
        )


skill = PriceAlertSkill()
