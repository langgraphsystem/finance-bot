"""Manage member skill — change role, suspend, or remove a member."""

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


class ManageMemberSkill:
    name = "manage_member"
    intents = ["manage_member"]
    model = "gpt-5.4-2026-03-05"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        if not context.has_permission("manage_members"):
            return SkillResult(response_text="You don't have permission to manage members.")

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
            return SkillResult(response_text="No members found in this workspace.")

        lines = ["<b>Manage members</b>\n"]
        buttons: list[dict[str, str]] = []

        for membership, user_name in rows:
            emoji = _ROLE_EMOJI.get(membership.role.value, "\U0001f464")
            role_label = membership.role.value.replace("_", " ").title()
            display_name = user_name or "Unknown"
            mid = str(membership.id)

            lines.append(f"{emoji} <b>{display_name}</b> — {role_label}")

            # Don't show action buttons for owners (can't demote/remove yourself)
            if membership.role.value == "owner":
                continue

            buttons.append(
                {"text": f"Change role: {display_name}", "callback": f"member:role:{mid}"}
            )
            buttons.append(
                {"text": f"Suspend: {display_name}", "callback": f"member:suspend:{mid}"}
            )
            buttons.append(
                {"text": f"Remove: {display_name}", "callback": f"member:remove:{mid}"}
            )

        if not buttons:
            lines.append("\nNo manageable members (only owners found).")

        return SkillResult(response_text="\n".join(lines), buttons=buttons)

    def get_system_prompt(self, context: SessionContext) -> str:
        return "You manage workspace members."


skill = ManageMemberSkill()
