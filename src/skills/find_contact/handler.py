"""Find contact skill — search contacts by name, phone, or role."""

import logging
from typing import Any

from sqlalchemy import or_, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.contact import Contact
from src.core.observability import observe
from src.core.search_utils import ilike_all_words, split_search_words
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

FIND_CONTACT_PROMPT = """\
You help users search for contacts in their CRM.
Extract the search query (name, phone, or keyword).
ALWAYS respond in the same language as the user's message/query."""


class FindContactSkill:
    name = "find_contact"
    intents = ["find_contact"]
    model = "gpt-5.2"

    @observe(name="find_contact")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("contact_name") or intent_data.get("search_query") or message.text or ""
        )
        query = query.strip()
        if not query:
            return SkillResult(response_text="Who are you looking for?")

        words = split_search_words(query)
        async with async_session() as session:
            if words:
                search_condition = or_(
                    ilike_all_words(Contact.name, words),
                    ilike_all_words(Contact.phone, words),
                    ilike_all_words(Contact.email, words),
                )
            else:
                pattern = f"%{query}%"
                search_condition = or_(
                    Contact.name.ilike(pattern),
                    Contact.phone.ilike(pattern),
                    Contact.email.ilike(pattern),
                )
            result = await session.execute(
                select(Contact)
                .where(Contact.family_id == context.family_id, search_condition)
                .order_by(Contact.name)
                .limit(20)
            )
            contacts = result.scalars().all()

        if not contacts:
            return SkillResult(response_text=f"No contacts found matching '{query}'.")

        lines = [f"<b>Found {len(contacts)} contact(s):</b>\n"]
        for c in contacts:
            line = f"- <b>{c.name}</b>"
            if c.phone:
                line += f" | {c.phone}"
            if c.email:
                line += f" | {c.email}"
            lines.append(line)

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return FIND_CONTACT_PROMPT.format(language=context.language or "en")


skill = FindContactSkill()
