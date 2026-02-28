"""Approval graph nodes — interrupt for HITL, then execute."""

import logging
from typing import Any

from langgraph.types import interrupt

from src.orchestrators.approval.state import ApprovalState

logger = logging.getLogger(__name__)


async def ask_approval(state: ApprovalState) -> dict[str, Any]:
    """Pause the graph and wait for user confirmation via ``interrupt()``.

    The interrupt payload contains the intent and action data so the
    router can render an appropriate preview with confirmation buttons.
    The user's answer (``"yes"`` or ``"no"``) is returned when the graph
    is resumed via ``Command(resume=answer)``.
    """
    answer = interrupt({
        "type": "pending_action_approval",
        "intent": state.get("intent", ""),
        "action_data": state.get("action_data", {}),
    })
    return {"approved": answer == "yes"}


async def execute_action(state: ApprovalState) -> dict[str, Any]:
    """Execute the confirmed action, or return cancellation message."""
    if not state.get("approved", False):
        return {"result_text": "Cancelled."}

    intent = state.get("intent", "")
    action_data = state.get("action_data", {})
    user_id = state.get("user_id", "")
    family_id = state.get("family_id", "")

    try:
        result_text = await _dispatch(intent, action_data, user_id, family_id)
    except Exception as e:
        logger.error("Approval action %s failed: %s", intent, e)
        result_text = "Error executing action. Please try again."

    return {"result_text": result_text}


async def _dispatch(
    intent: str,
    action_data: dict[str, Any],
    user_id: str,
    family_id: str,
) -> str:
    """Dispatch to the correct handler based on intent."""
    if intent == "send_email":
        from src.skills.send_email.handler import execute_send

        return await execute_send(action_data, user_id)

    if intent == "create_event":
        from src.skills.create_event.handler import execute_create_event

        return await execute_create_event(action_data, user_id)

    if intent == "reschedule_event":
        from src.skills.reschedule_event.handler import execute_reschedule

        return await execute_reschedule(action_data, user_id)

    if intent == "undo_last":
        from src.skills.undo_last.handler import execute_undo

        return await execute_undo(action_data, user_id, family_id)

    if intent == "delete_data":
        from src.skills.delete_data.handler import execute_delete

        return await execute_delete(action_data, user_id, family_id)

    if intent == "browser_action":
        from src.tools import browser_service

        result = await browser_service.execute_with_session(
            user_id=user_id,
            family_id=family_id,
            site=action_data.get("site", ""),
            task=action_data.get("task", ""),
        )
        if result["success"]:
            return result["result"]
        return f"Browser task failed: {result['result']}"

    if intent == "write_sheets":
        from src.skills.write_sheets.handler import execute_write_sheets

        return await execute_write_sheets(action_data, user_id)

    if intent == "data_tool_delete":
        from src.tools.data_tools import delete_record_confirmed

        return await delete_record_confirmed(
            family_id=family_id,
            user_id=user_id,
            table=action_data["table"],
            record_id=action_data["record_id"],
        )

    if intent == "delete_all":
        from src.core.db import async_session
        from src.core.gdpr import MemoryGDPR

        gdpr = MemoryGDPR()
        async with async_session() as session:
            await gdpr.delete_user_data(session, user_id)
        return "All your data has been deleted. Send /start to begin again."

    return "Unknown action."
