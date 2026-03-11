"""Synthetic voice QA scenarios for regression testing."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.context import SessionContext
from src.voice.evals import VoiceCallEvaluation, evaluate_voice_call
from src.voice.session_store import VoiceCallMetadata
from src.voice.summary import VoiceCallSummary, summarize_voice_call
from src.voice.trace import VoiceTraceEvent


@dataclass
class VoiceSimulationScenario:
    """Declarative synthetic voice call scenario."""

    scenario_id: str
    description: str
    metadata: VoiceCallMetadata
    context: SessionContext | None
    events: list[VoiceTraceEvent]
    duration_seconds: int
    expected_disposition: str
    min_score: int
    expected_flags: list[str] = field(default_factory=list)


@dataclass
class VoiceSimulationReport:
    """Result of running a synthetic voice scenario."""

    scenario_id: str
    passed: bool
    summary: VoiceCallSummary
    evaluation: VoiceCallEvaluation
    failures: list[str] = field(default_factory=list)


def run_voice_simulation(scenario: VoiceSimulationScenario) -> VoiceSimulationReport:
    """Evaluate one synthetic voice scenario."""
    summary = summarize_voice_call(
        scenario.metadata,
        scenario.context,
        scenario.events,
        scenario.duration_seconds,
    )
    evaluation = evaluate_voice_call(
        scenario.metadata,
        scenario.context,
        scenario.events,
        summary,
        scenario.duration_seconds,
    )

    failures: list[str] = []
    if summary.disposition != scenario.expected_disposition:
        failures.append(
            f"Expected disposition {scenario.expected_disposition}, got {summary.disposition}"
        )
    if evaluation.score < scenario.min_score:
        failures.append(f"Expected score >= {scenario.min_score}, got {evaluation.score}")
    missing_flags = [
        flag for flag in scenario.expected_flags if flag not in evaluation.flags
    ]
    if missing_flags:
        failures.append(f"Missing expected QA flags: {', '.join(missing_flags)}")

    return VoiceSimulationReport(
        scenario_id=scenario.scenario_id,
        passed=not failures,
        summary=summary,
        evaluation=evaluation,
        failures=failures,
    )


def builtin_voice_simulations() -> list[VoiceSimulationScenario]:
    """Return the built-in synthetic regression scenarios."""
    return [
        VoiceSimulationScenario(
            scenario_id="inbound_booking_success",
            description="Known caller books successfully without approval.",
            metadata=VoiceCallMetadata(
                call_id="sim-booking-success",
                call_type="inbound",
                owner_name="David",
                business_name="North Star Plumbing",
                services="plumbing",
                hours="Mon-Fri 9-5",
                from_phone="+15551234567",
            ),
            context=SessionContext(
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
            ),
            events=[
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:00Z",
                    kind="call_started",
                    payload={"call_type": "inbound"},
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:10Z",
                    kind="tool_requested",
                    payload={"tool_name": "create_booking"},
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:12Z",
                    kind="tool_completed",
                    payload={"tool_name": "create_booking", "ok": True},
                ),
            ],
            duration_seconds=82,
            expected_disposition="completed_with_tools",
            min_score=85,
        ),
        VoiceSimulationScenario(
            scenario_id="sensitive_request_approval",
            description="Inbound sensitive request gets routed to owner approval.",
            metadata=VoiceCallMetadata(
                call_id="sim-approval",
                call_type="inbound",
                owner_name="David",
                business_name="North Star Plumbing",
                services="plumbing",
                hours="Mon-Fri 9-5",
                from_phone="+15557654321",
            ),
            context=SessionContext(
                user_id="11111111-1111-1111-1111-111111111111",
                family_id="22222222-2222-2222-2222-222222222222",
                role="owner",
                language="en",
                currency="USD",
                business_type="plumber",
                categories=[],
                merchant_mappings=[],
                channel="voice",
                channel_user_id="+15557654321",
                voice_auth_state="anonymous",
            ),
            events=[
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:00Z",
                    kind="call_started",
                    payload={"call_type": "inbound"},
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:09Z",
                    kind="tool_requested",
                    payload={"tool_name": "send_to_client"},
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:10Z",
                    kind="tool_completed",
                    payload={
                        "tool_name": "send_to_client",
                        "ok": True,
                        "approval_requested": True,
                    },
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:10Z",
                    kind="approval_requested",
                    payload={"tool_name": "send_to_client"},
                ),
            ],
            duration_seconds=48,
            expected_disposition="approval_requested",
            min_score=85,
        ),
        VoiceSimulationScenario(
            scenario_id="realtime_failure",
            description="Transport failure is flagged for operator review.",
            metadata=VoiceCallMetadata(
                call_id="sim-failure",
                call_type="inbound",
                owner_name="David",
                business_name="North Star Plumbing",
                services="plumbing",
                hours="Mon-Fri 9-5",
                from_phone="+15550001111",
            ),
            context=None,
            events=[
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:00Z",
                    kind="call_started",
                    payload={"call_type": "inbound"},
                ),
                VoiceTraceEvent(
                    timestamp="2026-03-10T00:00:07Z",
                    kind="realtime_error",
                    payload={"message": "upstream disconnected"},
                ),
            ],
            duration_seconds=19,
            expected_disposition="error",
            min_score=40,
            expected_flags=["realtime_error"],
        ),
    ]


def run_builtin_voice_simulations() -> list[VoiceSimulationReport]:
    """Execute all built-in synthetic scenarios."""
    return [run_voice_simulation(scenario) for scenario in builtin_voice_simulations()]
