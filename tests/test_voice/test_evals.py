"""Tests for heuristic voice QA evaluation."""

from src.core.context import SessionContext
from src.voice.evals import evaluate_voice_call
from src.voice.session_store import VoiceCallMetadata
from src.voice.summary import VoiceCallSummary
from src.voice.trace import VoiceTraceEvent


def _context(auth_state: str = "matched_by_number") -> SessionContext:
    return SessionContext(
        user_id="11111111-1111-1111-1111-111111111111",
        family_id="22222222-2222-2222-2222-222222222222",
        role="owner",
        language="en",
        currency="USD",
        business_type="plumber",
        categories=[],
        merchant_mappings=[],
        channel="voice",
        channel_user_id="+15551234567",
        voice_auth_state=auth_state,
        voice_contact_name="John",
    )


def _metadata() -> VoiceCallMetadata:
    return VoiceCallMetadata(
        call_id="call-123",
        call_type="inbound",
        owner_name="David",
        business_name="North Star Plumbing",
        services="plumbing",
        hours="Mon-Fri 9-5",
        from_phone="+15551234567",
    )


def test_evaluate_voice_call_flags_realtime_failure():
    evaluation = evaluate_voice_call(
        _metadata(),
        None,
        [
            VoiceTraceEvent(
                timestamp="2026-03-10T00:00:00Z",
                kind="realtime_error",
                payload={"message": "fail"},
            )
        ],
        VoiceCallSummary(
            disposition="error",
            text="summary",
            tool_names=[],
            approvals_requested=0,
        ),
        duration_seconds=20,
    )

    assert evaluation.qa_status == "review"
    assert "realtime_error" in evaluation.flags
    assert evaluation.score == 60


def test_evaluate_voice_call_flags_sensitive_action_without_trust():
    evaluation = evaluate_voice_call(
        _metadata(),
        _context(auth_state="anonymous"),
        [
            VoiceTraceEvent(
                timestamp="2026-03-10T00:00:00Z",
                kind="tool_requested",
                payload={"tool_name": "send_to_client"},
            ),
            VoiceTraceEvent(
                timestamp="2026-03-10T00:00:01Z",
                kind="tool_completed",
                payload={"tool_name": "send_to_client", "ok": True},
            ),
        ],
        VoiceCallSummary(
            disposition="completed_with_tools",
            text="summary",
            tool_names=["send_to_client"],
            approvals_requested=0,
        ),
        duration_seconds=65,
    )

    assert evaluation.qa_status == "review"
    assert "sensitive_action_without_trust" in evaluation.flags
    assert evaluation.score == 75
