"""Action approval system — inline confirmation for side-effect actions.

Actions that modify external state (send email, create calendar event,
execute browser task) require explicit user confirmation before execution.

Flow:
1. Skill calls ``request_approval(action, data, summary)``
2. Bot shows summary + [Confirm] [Cancel] buttons
3. User taps button → callback routed to ``handle_approval`` / ``handle_rejection``
4. On confirm: execute the action, return result
5. On cancel: return cancellation message
"""

import json
import logging
import uuid
from typing import Any

from src.core.db import redis
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Pending approvals expire after 10 minutes
APPROVAL_TTL_S = 600


class ApprovalManager:
    """Manages pending user approvals via inline keyboard buttons."""

    async def request_approval(
        self,
        user_id: str,
        action: str,
        data: dict[str, Any],
        summary: str,
    ) -> SkillResult:
        """Store pending action and return a SkillResult with confirmation buttons."""
        approval_id = str(uuid.uuid4())[:8]

        payload = json.dumps({
            "action": action,
            "data": data,
            "user_id": user_id,
        })
        await redis.setex(f"approval:{approval_id}", APPROVAL_TTL_S, payload)

        return SkillResult(
            response_text=f"{summary}\n\nConfirm this action?",
            buttons=[
                {"text": "Confirm", "callback": f"confirm_action:{approval_id}"},
                {"text": "Cancel", "callback": f"cancel_action:{approval_id}"},
            ],
        )

    async def get_pending(self, approval_id: str) -> dict[str, Any] | None:
        """Retrieve a pending approval. Returns None if expired or not found."""
        raw = await redis.get(f"approval:{approval_id}")
        if not raw:
            return None
        return json.loads(raw)

    async def consume(self, approval_id: str) -> dict[str, Any] | None:
        """Retrieve and delete a pending approval (one-time use)."""
        raw = await redis.getdel(f"approval:{approval_id}")
        if not raw:
            return None
        return json.loads(raw)

    async def handle_rejection(self, approval_id: str) -> SkillResult:
        """Cancel a pending action."""
        await redis.delete(f"approval:{approval_id}")
        return SkillResult(response_text="Action cancelled.")


# Module-level singleton
approval_manager = ApprovalManager()
