"""Send to client skill — send messages or initiate calls to clients."""

import logging
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.contact import Contact
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SEND_TO_CLIENT_PROMPT = """\
You help business owners communicate with their clients.
Extract: client name, message content, and channel preference (SMS/WhatsApp/call).
ALWAYS respond in the same language as the user's message/query."""


class SendToClientSkill:
    name = "send_to_client"
    intents = ["send_to_client"]
    model = "gpt-5.2"

    @observe(name="send_to_client")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        contact_name = intent_data.get("contact_name") or ""
        contact_name = contact_name.strip()
        if not contact_name:
            return SkillResult(response_text="Who should I message? Give me the client's name.")

        msg_text = (
            intent_data.get("description")
            or intent_data.get("email_body_hint")
            or message.text
            or ""
        ).strip()

        # Find the contact
        async with async_session() as session:
            result = await session.execute(
                select(Contact)
                .where(
                    Contact.family_id == context.family_id,
                    Contact.name.ilike(f"%{contact_name}%"),
                )
                .limit(1)
            )
            contact = result.scalar_one_or_none()

        if not contact:
            return SkillResult(
                response_text=(
                    f"No contact found matching '{contact_name}'. "
                    "Add them first with 'add contact: Name, phone'."
                )
            )

        if not contact.phone:
            return SkillResult(response_text=f"{contact.name} has no phone number on file.")

        # Present confirmation with send button
        preview = (
            f"<b>Send to {contact.name}:</b>\n"
            f"Phone: {contact.phone}\n\n"
            f'"{msg_text}"\n\n'
            "Choose how to send:"
        )

        return SkillResult(
            response_text=preview,
            buttons=[
                {
                    "text": "SMS",
                    "callback": f"send_sms:{contact.id}:{msg_text[:100]}",
                },
                {
                    "text": "Call",
                    "callback": f"call_client:{contact.id}",
                },
                {
                    "text": "Cancel",
                    "callback": "cancel_send",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SEND_TO_CLIENT_PROMPT.format(language=context.language or "en")


skill = SendToClientSkill()
