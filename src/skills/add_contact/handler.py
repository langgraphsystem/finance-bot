"""Add contact skill — save a new client/contact to CRM."""

import logging
import uuid
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.contact import Contact
from src.core.models.enums import ContactRole
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

ADD_CONTACT_PROMPT = """\
You help users add contacts and clients to their CRM.
Extract: name (required), phone, email, role (client/vendor/partner/friend/family/doctor/other).
Respond in the user's preferred language: {language}."""


class AddContactSkill:
    name = "add_contact"
    intents = ["add_contact"]
    model = "gpt-5.2"

    @observe(name="add_contact")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        name = intent_data.get("contact_name") or ""
        name = name.strip()
        if not name:
            return SkillResult(response_text="What's the contact's name?")

        phone = intent_data.get("contact_phone")
        email = intent_data.get("contact_email")
        role_raw = intent_data.get("booking_contact_role", "client")
        try:
            role = ContactRole(role_raw)
        except ValueError:
            role = ContactRole.client

        contact = Contact(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            name=name,
            phone=phone,
            email=email,
            role=role,
        )

        async with async_session() as session:
            session.add(contact)
            await session.commit()

        parts = [f"Added contact: <b>{name}</b>"]
        if phone:
            parts.append(f"Phone: {phone}")
        if email:
            parts.append(f"Email: {email}")

        return SkillResult(response_text="\n".join(parts))

    def get_system_prompt(self, context: SessionContext) -> str:
        return ADD_CONTACT_PROMPT.format(language=context.language or "en")


skill = AddContactSkill()
