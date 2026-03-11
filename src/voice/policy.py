"""Voice-specific caller identity and risk policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.contact import Contact
from src.voice.session_store import VoiceCallMetadata

_LOW_RISK_TOOLS = {"receptionist", "find_available_slots", "take_message"}
_MATCHED_CALLER_TOOLS = {"create_booking"}
_VERIFICATION_TOOLS = {
    "request_verification",
    "verify_caller",
    "handoff_to_owner",
    "schedule_callback",
}
_VERIFIED_CALLER_TOOLS = {"confirm_booking", "reschedule_booking", "cancel_booking"}
_OWNER_APPROVAL_TOOLS = {
    "find_contact",
    "send_to_client",
    "create_event",
    "reschedule_event",
    "set_reminder",
    "create_task",
}


@dataclass
class VoiceCallerIdentity:
    """Caller identity resolved from the phone number."""

    auth_state: str
    phone_number: str = ""
    contact_id: str | None = None
    contact_name: str | None = None


@dataclass
class VoicePolicyDecision:
    """Result of checking a voice tool against caller trust and risk policy."""

    allow: bool
    requires_approval: bool = False
    message: str = ""
    summary: str = ""
    risk_tier: str = "public_info"


def normalize_phone(phone_number: str) -> str:
    """Normalize a phone number for loose comparisons."""
    digits = "".join(ch for ch in phone_number if ch.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        return digits[1:]
    return digits


async def resolve_caller_identity(
    family_id: str,
    phone_number: str,
) -> VoiceCallerIdentity:
    """Resolve the inbound caller to a known CRM contact by phone number."""
    normalized = normalize_phone(phone_number)
    if not normalized:
        return VoiceCallerIdentity(auth_state="anonymous")

    async with async_session() as session:
        result = await session.execute(
            select(Contact).where(
                Contact.family_id == family_id,
                Contact.phone.is_not(None),
            )
        )
        contacts = result.scalars().all()

    for contact in contacts:
        if normalize_phone(contact.phone or "") == normalized:
            return VoiceCallerIdentity(
                auth_state="matched_by_number",
                phone_number=phone_number,
                contact_id=str(contact.id),
                contact_name=contact.name,
            )

    return VoiceCallerIdentity(auth_state="anonymous", phone_number=phone_number)


def evaluate_voice_policy(
    context: SessionContext,
    metadata: VoiceCallMetadata,
    tool_name: str,
    arguments: dict[str, Any],
) -> VoicePolicyDecision:
    """Evaluate whether a voice tool call can execute immediately."""
    caller = context.voice_contact_name or context.voice_phone_number or "the caller"
    auth_state = context.voice_auth_state

    if context.role != "owner" and tool_name in _OWNER_APPROVAL_TOOLS | _VERIFIED_CALLER_TOOLS:
        return VoicePolicyDecision(
            allow=False,
            requires_approval=True,
            message="This request needs owner approval before I can complete it.",
            summary=_build_summary(tool_name, arguments, metadata, caller),
            risk_tier="owner_approval",
        )

    if tool_name in _VERIFICATION_TOOLS:
        return VoicePolicyDecision(allow=True, risk_tier="verification")

    if tool_name in _LOW_RISK_TOOLS:
        return VoicePolicyDecision(allow=True, risk_tier="public_info")

    if tool_name in _MATCHED_CALLER_TOOLS:
        if auth_state in {"matched_by_number", "verified_by_sms"}:
            return VoicePolicyDecision(allow=True, risk_tier="booking_safe")
        return VoicePolicyDecision(
            allow=False,
            requires_approval=True,
            message=(
                "I can take the request, but I need owner approval before I finalize the booking."
            ),
            summary=_build_summary(tool_name, arguments, metadata, caller),
            risk_tier="booking_safe",
        )

    if tool_name in _VERIFIED_CALLER_TOOLS:
        if metadata.call_type == "outbound":
            return VoicePolicyDecision(allow=True, risk_tier="booking_update")
        if auth_state in {"matched_by_number", "verified_by_sms"}:
            return VoicePolicyDecision(allow=True, risk_tier="booking_update_verified")
        return VoicePolicyDecision(
            allow=False,
            requires_approval=True,
            message=(
                "I need to verify the caller or get owner approval before changing this booking."
            ),
            summary=_build_summary(tool_name, arguments, metadata, caller),
            risk_tier="booking_update",
        )

    if tool_name in _OWNER_APPROVAL_TOOLS:
        return VoicePolicyDecision(
            allow=False,
            requires_approval=True,
            message="I need owner approval before doing that.",
            summary=_build_summary(tool_name, arguments, metadata, caller),
            risk_tier="owner_approval",
        )

    return VoicePolicyDecision(
        allow=False,
        message="That action is not allowed in voice mode yet.",
        risk_tier="blocked",
    )


def _build_summary(
    tool_name: str,
    arguments: dict[str, Any],
    metadata: VoiceCallMetadata,
    caller: str,
) -> str:
    """Build a short Telegram approval summary for a voice-originated action."""
    action_label = tool_name.replace("_", " ")
    business_name = metadata.business_name or metadata.owner_name
    return (
        f"Voice approval requested for <b>{action_label}</b>\n\n"
        f"Caller: {caller}\n"
        f"Business: {business_name}\n"
        f"Arguments: <code>{arguments}</code>"
    )
