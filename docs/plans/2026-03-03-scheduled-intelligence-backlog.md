# Backlog: Scheduled Intelligence Actions (SIA)

Date: 2026-03-03  
Status: Proposed  
Owner: Product + Core Platform

## 1. Planning Assumptions

1. Python 3.12+, async SQLAlchemy, Taskiq worker model remain unchanged.
2. Delivery channel in this phase is Telegram.
3. Existing reminders (`set_reminder` + `dispatch_due_reminders`) remain backward-compatible.
4. Model IDs must stay within approved set.

## 2. Priority Legend

1. `P0` - launch blockers.
2. `P1` - strong parity requirements.
3. `P2` - differentiation and optimization.

## 3. Epic Backlog

## Epic A - Data Foundation (`P0`)

### A1. Create `scheduled_actions` model + migration

1. Add SQLAlchemy model.
2. Add Alembic migration with indexes.
3. Add downgrade path.

Acceptance:

1. Table created with required fields.
2. Indexes present and validated in migration test.

Estimate: 2 days

### A2. Create `scheduled_action_runs` model + migration

1. Add run log table.
2. Add unique constraint `(scheduled_action_id, planned_run_at)`.

Acceptance:

1. Duplicate insert for same action/time fails deterministically.

Estimate: 1 day

### A3. Add enums/constants for schedule and status

1. Add schedule/status enums.
2. Add mapping helpers.

Acceptance:

1. Type-safe usage in handlers and tasks.

Estimate: 0.5 day

---

## Epic B - Intent and Skills (`P0`)

### B1. Add `schedule_action` intent support

1. Extend `intent.py` prompt rules and examples.
2. Add schema fields in `IntentData`.
3. Add tests for RU/EN phrasing.

Acceptance:

1. Intent detection catches one-shot and recurring schedule requests with >=0.8 confidence in tests.

Estimate: 1.5 days

### B2. Implement `schedule_action` skill

1. Parse intent data and context.
2. Clarify missing fields (what/when/sources).
3. Persist action and compute `next_run_at`.

Acceptance:

1. Returns Telegram HTML confirmation.
2. Persists valid row with UTC `next_run_at`.

Estimate: 2 days

### B3. Implement `list_scheduled_actions` skill

1. Query active/paused actions.
2. Render compact list with status and next run.

Acceptance:

1. Correctly returns empty state and multi-item state.

Estimate: 1 day

### B4. Implement `manage_scheduled_action` skill

1. Pause/resume/delete/reschedule pathways.
2. Ownership and family checks.

Acceptance:

1. User cannot mutate actions outside own family/user scope.

Estimate: 1.5 days

---

## Epic C - Dispatcher Engine (`P0`)

### C1. Add `dispatch_scheduled_actions` Taskiq cron

1. Register in `src/core/tasks/scheduled_action_tasks.py`.
2. Wire module into worker entrypoint.

Acceptance:

1. Cron runs every minute and processes due actions.

Estimate: 1 day

### C2. Implement idempotent run executor

1. Use transactional fetch + lock (`SKIP LOCKED`).
2. Create run record before processing.
3. Handle duplicate run collision gracefully.

Acceptance:

1. No duplicate sends in concurrency test.

Estimate: 2 days

### C3. Retry and failure policy

1. Exponential backoff for transient errors.
2. Pause action after max failures.

Acceptance:

1. Failures increment counters and state transitions are logged.

Estimate: 1 day

---

## Epic D - Data Collection and Formatting (`P0`)

### D1. Extract shared collectors

1. Move reusable logic from brief nodes into shared collector module.
2. Keep old brief behavior unchanged via adapter wrappers.

Acceptance:

1. Brief orchestrator tests remain green.
2. New engine can call same collectors.

Estimate: 2 days

### D2. Implement formatter modes

1. `compact` template mode.
2. `decision_ready` mode with optional LLM synthesis.

Acceptance:

1. Output uses Telegram HTML only.
2. Degraded mode clearly marks unavailable sources.

Estimate: 1.5 days

### D3. Multi-model fallback chain

1. Primary synthesis on `claude-sonnet-4-6`.
2. Fallback to `gpt-5.2`.
3. Cheap summary fallback on `gemini-3-flash-preview`.

Acceptance:

1. Tests verify fallback path on injected provider failure.

Estimate: 1 day

---

## Epic E - Telegram Interaction (`P0`)

### E1. Add `sched:*` callbacks to router

1. Parse callback payload.
2. Route to scheduler management handlers.

Acceptance:

1. `snooze`, `pause`, `resume`, `run_now`, `delete` all return deterministic responses.

Estimate: 1 day

### E2. Inline action buttons in scheduled messages

1. Add button rendering contract.
2. Respect channel constraints.

Acceptance:

1. Buttons render correctly via Telegram gateway and callbacks execute.

Estimate: 0.5 day

---

## Epic F - Market Parity Enhancements (`P1`)

### F1. Weekdays schedule support

Acceptance:

1. Mon-Fri trigger in user timezone with DST-safe behavior.

Estimate: 1 day

### F2. Custom cron schedule support

Acceptance:

1. Cron validation and safe parser; invalid cron gets user clarification.

Estimate: 1.5 days

### F3. End conditions (`end_at`, `max_runs`)

Acceptance:

1. Action auto-completes and no longer dispatches once condition reached.

Estimate: 1 day

### F4. Natural-language edit flow

Acceptance:

1. "Move my morning brief to 8:30" updates existing action without recreation.

Estimate: 1.5 days

---

## Epic G - Differentiators (`P2`)

### G1. Decision-ready output mode

Acceptance:

1. Message includes top priorities + one recommended next action.

Estimate: 1 day

### G2. Finance-aware overlay

Acceptance:

1. Budget/risk snippets appear when finance source is enabled and data available.

Estimate: 1 day

### G3. Outcome-based reminders

Acceptance:

1. "Until done" mode keeps schedule active until explicit completion callback.

Estimate: 1.5 days

### G4. Trust footer (freshness/source status)

Acceptance:

1. Each message can include source freshness and missing-source markers.

Estimate: 1 day

---

## Epic H - Observability and Operations (`P0/P1`)

### H1. Add metrics and logs

1. Triggered/succeeded/failed/partial counters.
2. Duration and model usage metrics.

Acceptance:

1. Dashboard queries and alerts can be built from emitted fields.

Estimate: 1 day

### H2. Add cleanup/retention for run logs

Acceptance:

1. Old run logs pruned by policy without deleting active action state.

Estimate: 0.5 day

### H3. Runbook + alerts

Acceptance:

1. Documented actions for high failure rate, send failures, queue lag.

Estimate: 0.5 day

---

## 4. Sprint Proposal

### Sprint 1 (P0 core)

1. A1, A2, B1, B2, C1, C2

### Sprint 2 (P0 completion)

1. B3, B4, C3, D1, D2, E1, E2, H1

### Sprint 3 (P1 parity)

1. F1, F2, F3, F4, H2, H3

### Sprint 4 (P2 differentiation)

1. G1, G2, G3, G4

## 5. Definition of Done

1. Unit + integration tests implemented and passing.
2. `ruff check` passes.
3. Backward compatibility validated for existing reminder and brief flows.
4. Rollout behind feature flag with staged activation plan.
5. Production telemetry and rollback steps documented.

