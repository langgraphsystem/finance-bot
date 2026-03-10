# Voice Production Implementation Plan

Date: 2026-03-10
Status: Proposed
Owner: Core Platform
Source: `docs/prds/booking-voice-crm.md` + `docs/prds/universal-receptionist.md` + current `src/voice/` implementation + market analysis as of 2026-03-10

## 1. Executive Summary

This project should not build a separate voice bot. Voice must become a first-class channel for the same assistant that already runs in Telegram.

Core principle:

1. One agent brain.
2. One permissions model.
3. One approval system.
4. One memory graph.
5. One CRM / booking / reminder source of truth.
6. One observability and audit trail.

Voice is only a transport and interaction layer for phone and realtime audio. All business logic, writes, approvals, memory updates, and multi-channel continuity stay in the existing Python backend.

Recommended stack:

1. OpenAI Realtime GA (`gpt-realtime` / `gpt-realtime-1.5`, with `gpt-realtime-mini` for cost-sensitive paths).
2. Twilio Voice / Media Streams for Phase 1 because the repo already contains a partial bridge.
3. Server-side tool execution in this repo.
4. Decagon-style product patterns copied into the platform where feasible: AOP-style playbooks, Trace View, Watchtower-like QA, simulations, experiments, layered guardrails, cross-channel memory, and operator insights.

Why migration is urgent:

1. Current code still uses `gpt-4o-realtime-preview` and `OpenAI-Beta: realtime=v1`.
2. OpenAI has scheduled both the Realtime beta interface and preview realtime models for shutdown on 2026-05-07.
3. Delaying migration creates near-term production risk.

## 2. Product Goal

The phone experience must be able to do the same kind of real work as the bot, within policy limits.

Required voice capabilities:

1. Answer inbound calls.
2. Handle receptionist questions using profile and specialist configuration.
3. Create, confirm, reschedule, and cancel bookings.
4. Take messages and create follow-up tasks.
5. Confirm appointments and perform outbound reminder / no-show / callback flows.
6. Trigger SMS / WhatsApp / Telegram follow-up through existing gateways.
7. Update CRM, reminders, memory, and calendar through the same backend logic.
8. Respect RBAC, visibility filtering, approval gates, and audit logging.

Non-goal:

1. Building a standalone voice-only decision engine.
2. Duplicating existing business logic in the voice layer.
3. Letting the model directly mutate state without backend validation.

## 3. Current State Snapshot

### 3.1 Existing reusable pieces

1. Voice transport utilities:
   1. `src/voice/audio.py`
   2. `src/voice/realtime.py`
   3. `src/voice/twilio_handler.py`
   4. `src/voice/call_manager.py`
2. Session and RBAC context:
   1. `src/core/context.py`
   2. `src/core/access.py`
   3. `src/core/request_context.py`
   4. `src/core/db.py`
3. Existing approval infrastructure:
   1. `src/core/approval.py`
   2. `src/core/pending_actions.py`
   3. `src/core/router.py`
4. Existing booking / receptionist product intent direction:
   1. `docs/prds/booking-voice-crm.md`
   2. `docs/prds/universal-receptionist.md`
5. Existing tests around basic voice utilities:
   1. `tests/test_voice/test_config.py`
   2. `tests/test_voice/test_twilio_handler.py`
   3. `tests/test_voice/test_call_manager.py`

### 3.2 Current blockers

1. `src/voice/config.py` still defaults to `gpt-4o-realtime-preview`.
2. `src/voice/realtime.py` still uses the beta header `OpenAI-Beta: realtime=v1`.
3. Current voice tools in `src/voice/twilio_handler.py` are not wired to the existing router / skills / policies.
4. No actual API route registration for `/webhook/voice/*` and `/ws/voice/*` was found in the repo scan; current support appears partial.
5. No production-grade call state machine exists yet.
6. No voice-specific observability, QA, or synthetic simulation framework exists yet.
7. No explicit caller identity trust model exists yet.
8. No voice-to-Telegram approval bridge exists yet.
9. Current project model whitelist in `AGENTS.md` does not include current OpenAI realtime model slugs.

### 3.3 Constraints

1. Do not introduce a second source of truth for bookings, contacts, reminders, or memory.
2. Voice must respect `SessionContext` permissions and visibility rules.
3. High-risk or destructive actions must not bypass current approval or pending-action patterns.
4. Telephony outages and model outages require graceful degradation.
5. Voice must remain multilingual and consistent with existing localization patterns.

## 4. External Baseline as of 2026-03-10

### 4.1 OpenAI Realtime conclusions

Use OpenAI Realtime as the core speech runtime.

Reasons:

1. GA realtime model family now exists (`gpt-realtime-1.5`, `gpt-realtime-mini`).
2. Official support includes WebRTC, WebSocket, and SIP.
3. OpenAI now documents server-side controls / sideband connections for SIP and WebRTC, which matches the architecture needed here: tool use and business logic remain private on the application server.
4. Current documented pricing supports production planning:
   1. `gpt-realtime-1.5` text input: $4 / 1M tokens
   2. `gpt-realtime-1.5` text output: $16 / 1M tokens
   3. `gpt-realtime-1.5` audio input: $32 / 1M tokens
   4. `gpt-realtime-1.5` audio output: $64 / 1M tokens
5. Structured outputs are not supported for `gpt-realtime`, so deterministic validation must stay in backend code.
6. Realtime transcription supports `audio/pcmu`, which is directly relevant to Twilio media streams.

### 4.2 Market positioning

Use these competitors as product references, not runtime dependencies.

1. Decagon: best reference for enterprise operating model, AOPs, QA, traceability, simulations, and cross-channel architecture.
2. Retell: best reference for managed phone-agent product surface.
3. ElevenLabs: best reference for high-quality voice and expressive speech.
4. LiveKit: best reference for infra-centric realtime agent runtime and telephony controls.
5. Vapi: best reference for test suites, evals, and fast deployment ergonomics.
6. Bland: best reference for outbound workflows, batch calling, transfer patterns, and memory continuity.

## 5. Decagon-Inspired Target Capability Set

The goal is not to clone Decagon branding. The goal is to replicate the useful platform ideas inside this repo where feasible.

### 5.1 Must-copy ideas

1. AOP-style playbooks.
2. Trace View for every conversation.
3. Watchtower-style always-on QA.
4. Synthetic simulations and regression replay.
5. Experiments and versioning for voice behavior.
6. Layered guardrails.
7. Cross-channel continuity.
8. Product and operator insights over conversations.

### 5.2 Mapping to this codebase

| Decagon concept | What it means | Repo implementation target |
|---|---|---|
| AOPs | Natural language workflow logic compiled into controlled steps | `src/voice/playbooks/` + YAML/MD playbook loader + step executor |
| Trace View | Per-turn visibility into reasoning and latency | `src/voice/trace.py` + DB event log + admin viewer later |
| Watchtower | QA on every conversation | `src/voice/evals.py` + `voice_eval_results` table + alert rules |
| Simulations | Replaying hard conversations and stress tests | `tests/test_voice/test_simulations_*.py` + fixtures |
| Experiments / A/B | Controlled prompt / playbook rollout | `voice_playbook_versions` table + version fields + config flags |
| Layered guardrails | Before, during, after conversation controls | `src/voice/policy.py` + approval bridge + post-call QA |
| Insights / Ask AI | Query and summarize operational patterns | `src/voice/analytics.py` + future operator/admin surface |
| Cross-channel memory | Voice and text share context and history | `SessionContext(channel="voice")` + existing memory pipelines |

## 6. Target Architecture

### 6.1 Architectural rule

Voice is a channel adapter, not a second agent runtime.

### 6.2 Major layers

1. Telephony / realtime transport layer
   1. inbound call webhook
   2. outbound call initiation
   3. media stream or SIP session management
   4. audio transcoding if Twilio bridge is used
2. Realtime conversation layer
   1. OpenAI realtime session
   2. server-side controls
   3. interruption handling
   4. turn-taking and VAD
3. Voice orchestration layer
   1. caller identity resolution
   2. call state machine
   3. policy checks
   4. tool routing
4. Unified application layer
   1. existing skills
   2. existing tools
   3. existing memory
   4. existing approvals
   5. existing notifications and gateways
5. Observability and QA layer
   1. traces
   2. metrics
   3. evaluations
   4. alerts
   5. simulations

### 6.3 Runtime flow

Inbound voice flow:

1. Phone call arrives.
2. Telephony adapter creates a `VoiceCallSession` and minimal context.
3. Caller identity is resolved by phone number and trust level is assigned.
4. OpenAI realtime session is started.
5. Realtime layer can speak and call backend tools, but tools are executed only by server code.
6. Tool adapter calls the same router / skills / backend flows used by the bot.
7. Policy layer blocks, confirms, or escalates risky actions.
8. Results are spoken back to the caller.
9. On completion, the call is persisted as interaction history, summary is generated, memory is updated, and the owner is notified in Telegram if needed.

Outbound voice flow:

1. Existing bot receives a text request to call or remind someone.
2. Existing approval flow confirms action when needed.
3. Voice subsystem places the outbound call.
4. The same backend tool / policy / audit layers apply.
5. Outcome is pushed back into Telegram, CRM, reminders, and memory.

## 7. Identity, Permissions, and Approval Model

### 7.1 SessionContext integration

Voice must instantiate the same `SessionContext` type used elsewhere.

Required additions to `SessionContext`:

1. `channel="voice"`
2. `channel_user_id` mapped to call session / phone identity
3. `voice_call_id`
4. `voice_auth_state`
5. `voice_trust_level`
6. `caller_phone`
7. optional `contact_id`

### 7.2 Caller trust levels

1. `anonymous`
2. `matched_by_phone`
3. `verified_low`
4. `verified_strong`
5. `owner_verified`

### 7.3 Action risk classes

1. `public_info`
2. `booking_safe`
3. `crm_update`
4. `sensitive_personal`
5. `financial`
6. `destructive`
7. `external_send`

### 7.4 Policy matrix

1. `public_info`
   1. allowed to anonymous callers
2. `booking_safe`
   1. allowed to matched or verified callers
3. `crm_update`
   1. allowed to verified callers
4. `sensitive_personal`
   1. requires strong verification or owner approval
5. `financial`
   1. never execute from anonymous voice alone
   2. require Telegram approval and identity validation
6. `destructive`
   1. require Telegram approval
7. `external_send`
   1. use existing approval pattern or pre-approved workflow policy

### 7.5 Approval bridge requirements

Voice must be able to say one of the following:

1. "I sent a confirmation to your Telegram."
2. "I can text you a secure confirmation link."
3. "I need the account owner to approve that action."

Implementation rule:

1. Reuse `src/core/approval.py` and pending-action patterns.
2. Do not create a separate voice-only approval store.

## 8. OpenAI Realtime Integration Plan

### 8.1 Migration target

Replace preview realtime integration with GA-compatible integration.

Required model support:

1. `gpt-realtime-1.5` or alias `gpt-realtime` for premium voice paths
2. `gpt-realtime-mini` for low-cost or internal paths
3. optional transcription mode using `gpt-4o-transcribe` or `gpt-4o-mini-transcribe`

### 8.2 Connection modes

Phase 1:

1. Server-side WebSocket bridge from Twilio Media Streams to OpenAI realtime.
2. Preserve current transcoding path where needed.

Phase 2:

1. Add sideband-capable architecture compatible with OpenAI SIP / WebRTC controls.
2. Keep tool use and business logic on application server.

Phase 3:

1. Evaluate whether direct SIP reduces complexity and latency enough to replace portions of Twilio bridge logic.

### 8.3 Realtime session rules

1. Prompt should define voice style, disclosure, fallback behavior, and repair strategy.
2. Prompt should not be the sole enforcement mechanism for business policy.
3. Tool calls must be backend-validated.
4. Realtime sessions must support interruption and barge-in.
5. Realtime session events must be logged into trace storage.

### 8.4 Audio path notes

1. Twilio Media Streams currently imply mu-law at 8 kHz.
2. Existing `src/voice/audio.py` already converts between mu-law 8 kHz and PCM16 16 kHz.
3. OpenAI realtime transcription docs now also support `audio/pcmu`, which opens a future optimization path for reducing custom transcoding complexity where appropriate.

## 9. File-by-File Change Map

### 9.1 Existing files to modify

1. `src/voice/config.py`
   1. Replace legacy preview model defaults.
   2. Add support for `gpt-realtime-1.5`, `gpt-realtime-mini`, transcription model config, policy toggles, and telephony mode flags.
2. `src/voice/realtime.py`
   1. Migrate off beta interface assumptions.
   2. Support current session schema.
   3. Add event normalization, sideband-compatible hooks, structured trace emission, and tool callback metadata.
3. `src/voice/twilio_handler.py`
   1. Stop treating tools as static local stubs.
   2. Delegate tool execution to a unified adapter.
   3. Add call setup / teardown hooks.
4. `src/voice/call_manager.py`
   1. Expand from basic persistence to session lifecycle orchestration.
   2. Persist richer metadata, disposition, and trace IDs.
5. `src/core/context.py`
   1. Extend `SessionContext` with voice metadata.
6. `src/core/router.py`
   1. Add voice-originated request entrypoints.
   2. Add approval continuation surfaces for voice handoff outcomes.
7. `src/core/approval.py`
   1. Add metadata for voice-originated approval requests.
8. `src/core/config.py`
   1. Add voice feature flags, eval thresholds, fallback toggles, alert thresholds.
9. `src/agents/base.py`
   1. Ensure tool executor path can be used from voice channel without Telegram-specific assumptions.
10. `src/agents/config.py`
   1. Expose channel-aware system guidance if needed.
11. `src/skills/receptionist/handler.py`
   1. Add voice-friendly result formatting path.
12. `src/core/notifications_pkg/templates.py`
   1. Add post-call summary templates and operator alert templates.
13. `tests/test_voice/test_config.py`
   1. Update realtime model expectations.
14. `tests/test_voice/test_twilio_handler.py`
   1. Update to reflect adapter-based tool architecture.
15. `tests/test_voice/test_call_manager.py`
   1. Expand for richer session behavior.

### 9.2 New modules to add

1. `src/voice/channel_adapter.py`
   1. Build `SessionContext` for voice calls.
   2. Resolve caller identity and contact linkage.
2. `src/voice/tool_adapter.py`
   1. Map realtime function calls to existing backend routes / skills.
3. `src/voice/policy.py`
   1. Risk classes, trust checks, approval requirements, sensitive action gating.
4. `src/voice/session_state.py`
   1. Explicit call state machine.
5. `src/voice/trace.py`
   1. Event logging and latency tracking.
6. `src/voice/evals.py`
   1. Watchtower-style post-call QA scoring.
7. `src/voice/playbooks/__init__.py`
8. `src/voice/playbooks/loader.py`
9. `src/voice/analytics.py`
   1. Aggregate call insights and future Ask-AI backend support.
10. `src/voice/escalation.py`
   1. Telegram / SMS / human handoff bridge.
11. `src/voice/identity.py`
   1. Phone-to-user / contact trust resolution and verification flows.
12. `src/voice/routes.py`
   1. Actual webhook / websocket route definitions if the project keeps a dedicated API surface.

### 9.3 New data models / migrations

1. `src/core/models/voice_call_session.py`
2. `src/core/models/voice_call_event.py`
3. `src/core/models/voice_eval_result.py`
4. `src/core/models/voice_playbook_version.py`
5. optional `src/core/models/caller_identity.py`
6. Alembic migration for the above.

### 9.4 New tests to add

1. `tests/test_voice/test_realtime_ga.py`
2. `tests/test_voice/test_channel_adapter.py`
3. `tests/test_voice/test_tool_adapter.py`
4. `tests/test_voice/test_policy.py`
5. `tests/test_voice/test_session_state.py`
6. `tests/test_voice/test_trace.py`
7. `tests/test_voice/test_evals.py`
8. `tests/test_voice/test_routes.py`
9. `tests/test_voice/test_simulations_inbound.py`
10. `tests/test_voice/test_simulations_outbound.py`
11. `tests/test_voice/test_approval_bridge.py`
12. `tests/test_voice/test_cross_channel_continuity.py`

## 10. Telephony and Route Integration Plan

### 10.1 Phase 1 route integration

Create actual callable routes for:

1. inbound voice webhook
2. outbound status webhook
3. voice websocket bridge
4. optional health endpoint for voice subsystem

### 10.2 Route registration requirement

If the project has no dedicated HTTP router module yet for voice, add one and explicitly wire it into the running application instead of leaving route intent inside docstrings.

### 10.3 Outbound call flow integration

1. Owner requests a call via existing bot channel.
2. Existing approval flow handles risky or external action confirmation.
3. Voice subsystem places outbound call.
4. Disposition is persisted and surfaced back into Telegram.

## 11. Same-Agent Tool Surface

Voice should expose a constrained set of callable tools at launch.

### 11.1 P0 launch tools

1. `receptionist_answer`
2. `find_available_slots`
3. `create_booking`
4. `reschedule_booking`
5. `cancel_booking`
6. `take_message`
7. `find_contact`
8. `create_task`
9. `set_reminder`
10. `send_client_message`
11. `handoff_to_owner`
12. `request_telegram_approval`

### 11.2 P1 tools

1. `confirm_booking`
2. `record_no_show`
3. `create_calendar_event`
4. `lookup_client_history`
5. `follow_up_last_week_clients`

### 11.3 P2 tools

1. `smart_slot_suggestion`
2. `location-aware travel window reasoning`
3. `customer verification workflow`
4. `voice-specific operator escalation`

## 12. Decagon-Style Playbooks (AOP Layer)

### 12.1 Why playbooks are required

Prompt-only behavior will become brittle as soon as voice handles multiple verticals and multi-step business actions.

### 12.2 Required playbooks

1. `receptionist_general`
2. `booking_new_client`
3. `booking_existing_client`
4. `appointment_confirmation_outbound`
5. `reschedule_negotiation`
6. `take_message_and_callback`
7. `escalate_to_owner`
8. `billing_or_sensitive_info_block`
9. `identity_verification_basic`
10. `call_failure_sms_fallback`

### 12.3 Playbook structure

Each playbook should define:

1. purpose
2. allowed actions
3. prohibited actions
4. required data collection order
5. confirmation requirements
6. escalation conditions
7. fallback wording
8. success criteria
9. QA criteria
10. version id

## 13. Observability, Trace View, and QA

### 13.1 Trace requirements

For each call, store:

1. call session metadata
2. caller identity resolution path
3. realtime session id
4. per-turn transcript fragments
5. model calls
6. tool calls
7. tool results
8. policy decisions
9. latency per step
10. final outcome / disposition

### 13.2 Watchtower-style QA requirements

Every call should be evaluated for:

1. task completion
2. policy compliance
3. hallucination risk
4. interruption handling
5. dead-air duration
6. caller frustration / sentiment shift
7. missed booking opportunity
8. failed verification behavior
9. fallback quality
10. escalation correctness

### 13.3 Alerting

Create alerts for:

1. call setup failure spike
2. dropped realtime sessions
3. long tool latency
4. repeated approval bridge failures
5. repeated hallucination flags
6. repeated no-summary failures
7. elevated first-turn hang-up rate

## 14. Synthetic Simulations and Regression Strategy

### 14.1 Required simulation scenarios

1. Anonymous caller asks business hours.
2. Existing client books an appointment.
3. Caller asks for a sensitive account action without verification.
4. Caller interrupts the agent repeatedly.
5. Noisy call quality with recovery.
6. Caller hangs up mid-booking.
7. Double-booking attempt.
8. Outbound confirmation where client reschedules.
9. RU call.
10. ES call.
11. Caller requests a task and SMS follow-up.
12. Owner approval required during call.
13. Model outage fallback.
14. Twilio bridge disconnect.
15. Operator escalation flow.

### 14.2 Replay tests from real traces

A production-grade requirement is to convert flagged real conversations into regression tests, following the same philosophy Decagon describes for Trace View + testing.

## 15. Cross-Channel Continuity Requirements

After a voice interaction, the platform must be able to:

1. Send owner summary in Telegram.
2. Send customer confirmation via SMS / WhatsApp if configured.
3. Write interaction history into CRM / client interactions.
4. Update memory and preferences if appropriate.
5. Create reminders / tasks / bookings in the same stores used by other channels.
6. Preserve a traceable audit trail.

## 16. Security and Compliance Considerations

1. Voice prompt must clearly disclose that the caller is speaking with an AI assistant where legally appropriate.
2. Recording / transcription consent rules must be configurable by locale or business profile.
3. Tool use and secrets must remain server-side.
4. Sensitive actions must never rely on caller speech alone when stronger verification is needed.
5. Personal and financial data redaction should be supported in stored traces where appropriate.
6. Rollout must include kill switches and degraded modes.

## 17. Rollout Phases

### Phase 0: Decision lock and guardrails

Goals:

1. Freeze architecture decisions.
2. Approve current OpenAI realtime target.
3. Approve risk classes and approval matrix.
4. Approve disclosure / recording policy.
5. Update internal model policy to allow current realtime model ids.

Deliverables:

1. This implementation plan approved.
2. ADR for voice architecture.
3. Feature flags specified.

### Phase 1: OpenAI Realtime GA migration

Goals:

1. Remove preview realtime usage.
2. Migrate `src/voice/realtime.py` and config.
3. Update tests.

Deliverables:

1. GA-compatible realtime client.
2. Updated config and tests.
3. No preview model slugs left in runtime code.

### Phase 2: Real route wiring and call session persistence

Goals:

1. Add actual voice routes.
2. Persist call sessions and events.
3. Wire Twilio bridge end-to-end.

Deliverables:

1. Inbound call path works end-to-end.
2. Outbound call path works end-to-end.
3. Session records persist.

### Phase 3: Same-agent integration

Goals:

1. Build `VoiceChannelAdapter`.
2. Build `VoiceToolAdapter`.
3. Route voice tools to the same backend logic.

Deliverables:

1. Voice uses `SessionContext(channel="voice")`.
2. Realtime tool calls execute through existing backend pathways.
3. No duplicate business logic in voice layer.

### Phase 4: Permissions, verification, and approval bridge

Goals:

1. Add trust model.
2. Add risk-based policy engine.
3. Bridge to Telegram approvals.

Deliverables:

1. Sensitive actions are gated correctly.
2. Voice cannot bypass RBAC or approvals.
3. Approval continuity across channels works.

### Phase 5: Decagon-style platform layer

Goals:

1. Add playbooks.
2. Add trace storage and latency metrics.
3. Add Watchtower-style evaluations.
4. Add synthetic simulations.

Deliverables:

1. Playbook-driven behavior.
2. Per-call trace view data model.
3. Always-on QA for calls.
4. Regression simulation suite.

### Phase 6: Insights, experiments, and rollout hardening

Goals:

1. Add analytics and operator insights.
2. Add versioning and experiments.
3. Add dashboards and alerts.
4. Pilot rollout and tuning.

Deliverables:

1. Versioned voice playbooks.
2. Experiment support.
3. Production dashboards and alerting.
4. Pilot report and rollout checklist.

## 18. Production Gates

Voice is not production-ready until all gates below are green.

1. No preview realtime models remain in active voice code.
2. Realtime beta header usage is removed.
3. Actual webhook / websocket routes are wired into the runtime.
4. Voice sessions create `SessionContext` with permissions.
5. Voice cannot bypass RBAC or visibility filters.
6. High-risk actions require stronger verification and / or Telegram approval.
7. Call sessions, events, and summaries persist correctly.
8. Operator alerts exist for transport and model failures.
9. Synthetic regression suite exists and runs in CI.
10. Post-call QA scoring exists.
11. Telegram / SMS fallback exists.
12. Kill switches and degraded receptionist-only mode exist.

## 19. Success Metrics

### Product metrics

1. 90 percent or higher inbound call answer rate.
2. 70 percent or higher task completion for eligible inbound calls.
3. 20 percent or lower first-10-second hang-up rate.
4. 95 percent or higher post-call summary delivery rate.
5. 95 percent or higher trace persistence success rate.

### Platform metrics

1. Median speech-to-first-response latency under 1200 ms target.
2. Median tool round-trip latency under 1500 ms target.
3. Less than 1 percent fatal call session failure rate.
4. Less than 2 percent missing transcript / summary rate.
5. 100 percent of destructive and financial actions policy-gated.

## 20. Immediate Next Step

Implement Phase 1 and Phase 2 in order:

1. migrate the existing `src/voice/` code to OpenAI Realtime GA
2. wire real voice routes and call session persistence
3. only then move to same-agent tool integration and Decagon-style platform features

## 21. Source Links

OpenAI:

1. https://developers.openai.com/api/docs/models/gpt-realtime-1.5
2. https://developers.openai.com/api/docs/deprecations
3. https://developers.openai.com/api/docs/guides/realtime-server-controls
4. https://developers.openai.com/api/docs/guides/realtime-transcription
5. https://openai.com/api/pricing/

Decagon:

1. https://decagon.ai/product/overview
2. https://decagon.ai/product/aop
3. https://decagon.ai/resources/decagon-trace-view
4. https://decagon.ai/resources/decagon-watchtower
5. https://decagon.ai/resources/introducing-experiments-ab-testing
6. https://decagon.ai/blog/series-d-announcement

Reference platforms:

1. https://docs.retellai.com/general/introduction
2. https://elevenlabs.io/docs/eleven-agents/overview
3. https://docs.livekit.io/agents/
4. https://docs.livekit.io/telephony/
5. https://docs.vapi.ai/phone-calling
6. https://docs.vapi.ai/test/test-suites/
7. https://docs.bland.ai/
