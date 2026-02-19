"""List contacts skill — show all contacts/clients."""

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

LIST_CONTACTS_PROMPT = """\
You help users view their contact list.
Format contacts clearly with name, phone, email, and role.
Respond in the user's preferred language: {language}."""


class ListContactsSkill:
    name = "list_contacts"
    intents = ["list_contacts"]
    model = "claude-haiku-4-5"

    @observe(name="list_contacts")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        async with async_session() as session:
            result = await session.execute(
                select(Contact)
                .where(Contact.family_id == context.family_id)
                .order_by(Contact.name)
                .limit(50)
            )
            contacts = result.scalars().all()

        if not contacts:
            return SkillResult(
                response_text="No contacts yet. Add one with 'add contact: Name, phone'."
            )

        lines = ["<b>Your contacts:</b>\n"]
        for c in contacts:
            line = f"- <b>{c.name}</b>"
            if c.phone:
                line += f" | {c.phone}"
            if c.role and c.role.value != "other":
                line += f" ({c.role.value})"
            lines.append(line)

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_CONTACTS_PROMPT.format(language=context.language or "en")


skill = ListContactsSkill()
