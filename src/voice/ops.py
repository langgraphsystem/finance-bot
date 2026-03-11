"""Operator-facing metrics and rollout state for voice."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.voice.config import VoiceConfig
from src.voice.review_store import VoiceCallReview


@dataclass
class VoiceOpsOverview:
    """Aggregated operator view over recent voice call reviews."""

    total_calls: int
    avg_duration_seconds: int
    qa_status_counts: dict[str, int] = field(default_factory=dict)
    disposition_counts: dict[str, int] = field(default_factory=dict)
    auth_state_counts: dict[str, int] = field(default_factory=dict)
    approvals_requested: int = 0
    callbacks_requested: int = 0
    handoffs_requested: int = 0
    verification_completed: int = 0
    flagged_calls: list[dict[str, object]] = field(default_factory=list)
    switches: dict[str, bool] = field(default_factory=dict)


def build_voice_ops_overview(
    reviews: list[VoiceCallReview],
    config: VoiceConfig,
) -> VoiceOpsOverview:
    """Build a compact dashboard snapshot from recent call reviews."""
    qa_status_counts = {"pass": 0, "review": 0, "fail": 0}
    disposition_counts: dict[str, int] = {}
    auth_state_counts: dict[str, int] = {}
    approvals_requested = 0
    callbacks_requested = 0
    handoffs_requested = 0
    verification_completed = 0
    total_duration = 0
    flagged_calls: list[dict[str, object]] = []

    for review in reviews:
        qa_status_counts[review.qa_status] = qa_status_counts.get(review.qa_status, 0) + 1
        disposition_counts[review.disposition] = disposition_counts.get(review.disposition, 0) + 1
        auth_state_counts[review.auth_state] = auth_state_counts.get(review.auth_state, 0) + 1
        approvals_requested += review.approvals_requested
        total_duration += review.duration_seconds

        if "schedule_callback" in review.tool_names:
            callbacks_requested += 1
        if "handoff_to_owner" in review.tool_names:
            handoffs_requested += 1
        if review.auth_state == "verified_by_sms":
            verification_completed += 1
        if review.qa_flags:
            flagged_calls.append(
                {
                    "call_id": review.call_id,
                    "qa_status": review.qa_status,
                    "qa_flags": review.qa_flags,
                    "disposition": review.disposition,
                }
            )

    avg_duration = int(total_duration / len(reviews)) if reviews else 0
    return VoiceOpsOverview(
        total_calls=len(reviews),
        avg_duration_seconds=avg_duration,
        qa_status_counts=qa_status_counts,
        disposition_counts=disposition_counts,
        auth_state_counts=auth_state_counts,
        approvals_requested=approvals_requested,
        callbacks_requested=callbacks_requested,
        handoffs_requested=handoffs_requested,
        verification_completed=verification_completed,
        flagged_calls=flagged_calls[:10],
        switches=config.rollout_state(),
    )
