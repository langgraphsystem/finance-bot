"""Tests for voice call summary generation."""

from src.core.context import SessionContext
from src.voice.session_store import VoiceCallMetadata
from src.voice.summary import summarize_voice_call
from src.voice.trace import VoiceTraceEvent


def _context() -> SessionContext:
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
        voice_auth_state="matched_by_number",
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


def test_summarize_voice_call_includes_tools_and_approvals():
    events = [
        VoiceTraceEvent(
            timestamp="2026-03-10T00:00:00Z",
            kind="tool_completed",
            payload={"tool_name": "create_booking"},
        ),
        VoiceTraceEvent(
            timestamp="2026-03-10T00:00:01Z",
            kind="approval_requested",
            payload={"tool_name": "create_event"},
        ),
    ]

    summary = summarize_voice_call(_metadata(), _context(), events, duration_seconds=95)

    assert summary.disposition == "approval_requested"
    assert summary.tool_names == ["create_booking"]
    assert summary.approvals_requested == 1
    assert "Caller: John" in summary.text
    assert "Duration: 95s" in summary.text
