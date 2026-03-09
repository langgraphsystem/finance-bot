"""Invite member skill — generate invite link with role selection."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Role descriptions for the wizard
_ROLE_DESCRIPTIONS = {
    "partner": "Full family access (finances, budgets, reports)",
    "family_member": "Basic family access (add expenses, view budgets)",
    "worker": "Work tasks and contacts only",
    "assistant": "Work tasks, contacts, documents",
    "accountant": "Full finance access (view, create, edit, reports)",
    "viewer": "Read-only access to shared data",
}


class InviteMemberSkill:
    name = "invite_member"
    intents = ["invite_member"]
    model = "gpt-5.2"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        if not context.has_permission("invite_members"):
            return SkillResult(response_text="You don't have permission to invite members.")

        # Step 1: Ask membership type
        return SkillResult(
            response_text="<b>Invite a new member</b>\n\nChoose membership type:",
            buttons=[
                {
                    "text": "\U0001f468\u200d\U0001f469\u200d\U0001f467 Family",
                    "callback": "invite:type:family",
                },
                {"text": "\U0001f4bc Worker", "callback": "invite:type:worker"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return "You help the user invite new members to their workspace."


skill = InviteMemberSkill()
