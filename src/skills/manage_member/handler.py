"""Manage member skill — change role, suspend, or remove a member."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


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

        # This skill is triggered by callbacks from list_members
        # The actual management is handled in callback handlers
        return SkillResult(
            response_text=(
                "<b>Member management</b>\n\n"
                "Use the member list to select a member to manage.\n"
                "You can change their role, suspend, or remove them."
            ),
            buttons=[
                {"text": "\U0001f4cb List members", "callback": "members:list"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return "You manage workspace members."


skill = ManageMemberSkill()
