"""Heuristic QA scoring for completed voice calls."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from src.core.context import SessionContext
from src.voice.session_store import VoiceCallMetadata
from src.voice.summary import VoiceCallSummary
from src.voice.trace import VoiceTraceEvent

HIGH_RISK_TOOLS = {
    "find_contact",
    "send_to_client",
    "create_event",
    "reschedule_event",
    "set_reminder",
    "create_task",
    "cancel_booking",
}


@dataclass
class VoiceCallEvaluation:
    """Structured QA evaluation for a voice call."""

    score: int
    qa_status: str
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)


def evaluate_voice_call(
    metadata: VoiceCallMetadata,
    context: SessionContext | None,
    events: list[VoiceTraceEvent],
    summary: VoiceCallSummary,
    duration_seconds: int,
) -> VoiceCallEvaluation:
    """Score a voice call using simple production-safe heuristics."""
    counts = Counter(event.kind for event in events)
    completed_tools = [
        str(event.payload.get("tool_name") or "")
        for event in events
        if event.kind == "tool_completed"
    ]
    auth_state = context.voice_auth_state if context else "unbound"

    score = 100
    flags: list[str] = []
    notes: list[str] = []

    if counts["realtime_error"]:
        score -= 40
        flags.append("realtime_error")
        notes.append("Realtime transport emitted one or more errors.")

    if counts["tool_requested"] > counts["tool_completed"]:
        score -= 20
        flags.append("incomplete_tool_execution")
        notes.append("At least one tool call started but did not complete.")

    if duration_seconds < 15 and not summary.tool_names and not summary.approvals_requested:
        score -= 15
        flags.append("short_unresolved_call")
        notes.append("The caller disconnected before the agent resolved anything.")

    if (
        metadata.call_type == "inbound"
        and duration_seconds >= 30
        and not summary.tool_names
        and not summary.approvals_requested
        and summary.disposition == "conversation_only"
    ):
        score -= 15
        flags.append("missed_resolution")
        notes.append("Inbound call ended without a tool action or approval handoff.")

    completed_high_risk = [tool for tool in completed_tools if tool in HIGH_RISK_TOOLS]
    if (
        completed_high_risk
        and auth_state in {"none", "unbound", "anonymous"}
        and not summary.approvals_requested
    ):
        score -= 25
        flags.append("sensitive_action_without_trust")
        notes.append("A sensitive tool completed without a verified caller identity.")

    if summary.approvals_requested:
        notes.append("Owner approval bridge was used for at least one action.")

    if summary.tool_names and not counts["realtime_error"]:
        notes.append("The call completed backend tool execution successfully.")

    if not notes:
        notes.append("No major QA signals were detected.")

    score = max(0, min(100, score))
    if score >= 85:
        qa_status = "pass"
    elif score >= 60:
        qa_status = "review"
    else:
        qa_status = "fail"

    return VoiceCallEvaluation(
        score=score,
        qa_status=qa_status,
        flags=flags,
        notes=notes,
        event_counts=dict(counts),
    )
