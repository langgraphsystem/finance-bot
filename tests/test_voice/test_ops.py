"""Tests for voice operator metrics aggregation."""

from src.voice.config import VoiceConfig
from src.voice.ops import build_voice_ops_overview
from src.voice.review_store import VoiceCallReview


def test_build_voice_ops_overview_counts_callbacks_and_handoffs():
    reviews = [
        VoiceCallReview(
            call_id="call-1",
            created_at="2026-03-10T00:00:00Z",
            call_type="inbound",
            caller="John",
            duration_seconds=60,
            disposition="completed_with_tools",
            summary_text="Summary",
            tool_names=["schedule_callback"],
            approvals_requested=1,
            auth_state="verified_by_sms",
            qa_score=90,
            qa_status="pass",
        ),
        VoiceCallReview(
            call_id="call-2",
            created_at="2026-03-10T00:01:00Z",
            call_type="inbound",
            caller="Jane",
            duration_seconds=30,
            disposition="approval_requested",
            summary_text="Summary",
            tool_names=["handoff_to_owner"],
            auth_state="anonymous",
            qa_score=55,
            qa_status="fail",
            qa_flags=["realtime_error"],
        ),
    ]

    overview = build_voice_ops_overview(reviews, VoiceConfig())

    assert overview.total_calls == 2
    assert overview.avg_duration_seconds == 45
    assert overview.callbacks_requested == 1
    assert overview.handoffs_requested == 1
    assert overview.verification_completed == 1
    assert overview.approvals_requested == 1
    assert overview.qa_status_counts["pass"] == 1
    assert overview.qa_status_counts["fail"] == 1
    assert overview.flagged_calls[0]["call_id"] == "call-2"
