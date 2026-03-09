"""List members skill — show all workspace members and their roles."""

import logging
import uuid
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.user import User
from src.core.models.workspace_membership import WorkspaceMembership
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_ROLE_EMOJI = {
    "owner": "\U0001f451",
    "partner": "\U0001f491",
    "family_member": "\U0001f468\u200d\U0001f469\u200d\U0001f467",
    "worker": "\U0001f4bc",
    "assistant": "\U0001f4cb",
    "accountant": "\U0001f4ca",
    "viewer": "\U0001f441",
}


class ListMembersSkill:
    name = "list_members"
    intents = ["list_members"]
    model = "gpt-5.4-2026-03-05"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        async with async_session() as session:
            stmt = (
                select(WorkspaceMembership, User.name)
                .join(User, WorkspaceMembership.user_id == User.id)
                .where(
                    WorkspaceMembership.family_id == uuid.UUID(context.family_id),
                    WorkspaceMembership.status == "active",
                )
                .order_by(WorkspaceMembership.role)
            )
            rows = (await session.execute(stmt)).all()

        if not rows:
            return SkillResult(response_text="No members found.")

        lines = ["<b>Team members</b>\n"]
        for membership, user_name in rows:
            emoji = _ROLE_EMOJI.get(membership.role.value, "\U0001f464")
            role_label = membership.role.value.replace("_", " ").title()
            mtype = membership.membership_type.value if membership.membership_type else ""
            lines.append(f"{emoji} <b>{user_name or 'Unknown'}</b> — {role_label} ({mtype})")

        # Only show manage button for users with manage_members permission
        buttons = []
        if context.has_permission("manage_members"):
            buttons.append({"text": "\u2699\ufe0f Manage", "callback": "members:manage"})
            buttons.append({"text": "\u2795 Invite", "callback": "members:invite"})

        return SkillResult(response_text="\n".join(lines), buttons=buttons)

    def get_system_prompt(self, context: SessionContext) -> str:
        return "You list workspace members."


skill = ListMembersSkill()
