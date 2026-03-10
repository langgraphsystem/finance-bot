"""Build post-call summaries from voice trace events."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.context import SessionContext
from src.voice.session_store import VoiceCallMetadata
from src.voice.trace import VoiceTraceEvent


@dataclass
class VoiceCallSummary:
    """Structured post-call summary."""

    disposition: str
    text: str
    tool_names: list[str]
    approvals_requested: int


def summarize_voice_call(
    metadata: VoiceCallMetadata,
    context: SessionContext | None,
    events: list[VoiceTraceEvent],
    duration_seconds: int,
) -> VoiceCallSummary:
    """Create a compact call summary suitable for CRM and Telegram."""
    tool_names = []
    approvals_requested = 0
    errors = 0

    for event in events:
        if event.kind == "tool_completed":
            tool_name = str(event.payload.get("tool_name") or "")
            if tool_name and tool_name not in tool_names:
                tool_names.append(tool_name)
        elif event.kind == "approval_requested":
            approvals_requested += 1
        elif event.kind == "realtime_error":
            errors += 1

    caller = (
        (context.voice_contact_name if context else None)
        or metadata.contact_name
        or metadata.from_phone
        or metadata.to_phone
        or "unknown caller"
    )
    auth_state = context.voice_auth_state if context else "unknown"
    tools_text = ", ".join(tool_names) if tool_names else "no tool calls"

    if errors:
        disposition = "error"
    elif approvals_requested:
        disposition = "approval_requested"
    elif tool_names:
        disposition = "completed_with_tools"
    else:
        disposition = "conversation_only"

    summary = (
        f"Voice call summary\n"
        f"Direction: {metadata.call_type}\n"
        f"Caller: {caller}\n"
        f"Auth: {auth_state}\n"
        f"Duration: {duration_seconds}s\n"
        f"Tools: {tools_text}\n"
        f"Approvals requested: {approvals_requested}\n"
        f"Disposition: {disposition}"
    )

    return VoiceCallSummary(
        disposition=disposition,
        text=summary,
        tool_names=tool_names,
        approvals_requested=approvals_requested,
    )
