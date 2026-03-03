# Backlog: Scheduled Intelligence Actions (SIA)

Date: 2026-03-03
Updated: 2026-03-03
Status: Proposed
Owner: Product + Core Platform

## 1. Planning Assumptions

1. Python 3.12+, async SQLAlchemy, Taskiq worker model remain unchanged.
2. Delivery channel in this phase is Telegram.
3. Existing reminders (`set_reminder` + `dispatch_due_reminders`) remain backward-compatible.
4. Model IDs must stay within approved set.
5. All user-facing text supports EN/RU/ES via i18n string tables.
6. Brief collectors reused via direct import (no refactoring).

## 2. Priority Legend

1. `P0` - launch blockers.
2. `P1` - strong parity requirements.
3. `P2` - differentiation and optimization.

## 3. Epic Backlog

## Epic A - Data Foundation (`P0`)

### A1. Create `scheduled_actions` model + migration

1. Add SQLAlchemy model with all columns per Tech Design §3.2.
2. Add Alembic migration with raw SQL (`CREATE TABLE IF NOT EXISTS`).
3. Add partial index `(status, next_run_at) WHERE status = 'active'`.
4. Add user index `(family_id, user_id, status)`.
5. Use `DO $$ ... EXCEPTION WHEN duplicate_object` for any enum types.
6. Add downgrade path.

Acceptance:

1. Table created with all 22 fields.
2. Indexes present and validated in migration test.
3. `alembic upgrade head` + `alembic downgrade -1` both succeed.

Estimate: 1.5 days

### A2. Create `scheduled_action_runs` model + migration

1. Add run log table with all 15 columns per Tech Design §3.2.
2. Add unique constraint `(scheduled_action_id, planned_run_at)`.
3. Add `ON DELETE CASCADE` for scheduled_action FK.

Acceptance:

1. Duplicate insert for same action/time raises `IntegrityError`.
2. Deleting a scheduled_action cascades to its runs.

Estimate: 1 day

### A3. Add enums, constants, and ScheduleConfig Pydantic model

1. Add `ScheduleKind`, `ActionStatus`, `RunStatus`, `OutputMode` enums.
2. Add `ScheduleConfig` Pydantic model with validation.
3. Add mapping helpers.

Acceptance:

1. Type-safe usage in handlers and tasks.
2. Invalid `ScheduleConfig` (e.g., `time="25:00"`) raises `ValidationError`.
3. All enum values match Tech Design §3.2.

Estimate: 0.5 day

### A4. Wire integration points

1. Add `ff_scheduled_actions` and `ff_sia_synthesis` to `src/core/config.py`.
2. Add 3 intent mappings to `src/core/domains.py` (`Domain.tasks`).
3. Add trigger keywords to `config/skill_catalog.yaml` (tasks domain).
4. Add `QUERY_CONTEXT_MAP` entries in `src/core/memory/context.py`.
5. Add `src.core.tasks.scheduled_action_tasks` to `scripts/entrypoint.sh` TASK_MODULES.

Acceptance:

1. Feature flags accessible via `settings.ff_scheduled_actions`.
2. Intent routing resolves to tasks domain.
3. Worker picks up new task module on startup.

Estimate: 0.5 day

---

## Epic B - Intent and Skills (`P0`)

### B1. Add `schedule_action` intent support

1. Extend `INTENT_DETECTION_PROMPT` in `src/core/intent.py` with examples (EN/RU).
2. Escape all literal curly braces with `{{}}`.
3. Add 9 `IntentData` fields per Tech Design §3.9.
4. Add tests for EN/RU/ES phrasing.

Acceptance:

1. Intent detection catches one-shot and recurring schedule requests with >=0.8 confidence in tests.
2. Fields `schedule_frequency`, `schedule_time`, `schedule_sources` correctly extracted.

Estimate: 1.5 days

### B2. Implement `schedule_action` skill

1. Parse intent data and context.
2. Validate `ScheduleConfig` from extracted fields.
3. Clarify missing fields (what/when/sources) via follow-up question.
4. Persist action and compute `next_run_at`.
5. Return i18n confirmation message.
6. Check `ff_scheduled_actions` gate.

Acceptance:

1. Returns Telegram HTML confirmation in user's language.
2. Persists valid row with UTC `next_run_at`.
3. Confirmation includes: schedule description, sources, next run time.
4. Returns gate message if feature disabled.

Estimate: 2 days

### B3. Implement `list_scheduled_actions` skill

1. Query active/paused actions for user.
2. Render i18n list with status icons, schedule description, next run time.
3. Show empty state with example prompt.

Acceptance:

1. Correctly returns empty state and multi-item state.
2. Status icons: ▶️ active, ⏸ paused, ✅ completed.
3. Times displayed in user's timezone with locale-appropriate format.
4. Output in user's language (EN/RU/ES).

Estimate: 1 day

### B4. Implement `manage_scheduled_action` skill

1. Pause/resume/delete/reschedule pathways.
2. Match action by title (fuzzy) or by list position.
3. Ownership and family checks.
4. Return i18n confirmation for each operation.

Acceptance:

1. User cannot mutate actions outside own family/user scope.
2. Pause sets `status='paused'`, resume sets `status='active'` + recomputes `next_run_at`.
3. Delete sets `status='deleted'`.
4. All responses in user's language.

Estimate: 1.5 days

### B5. Create i18n string tables

1. Create `src/core/scheduled_actions/i18n.py` with `_STRINGS` dict.
2. Add `t(key, lang, **kwargs)` accessor function.
3. Cover all keys: greetings, section headers, buttons, confirmations, errors, schedule descriptions.
4. Add date/time format helpers per locale.
5. Add weekday names per locale.

Acceptance:

1. All keys present for EN, RU, ES.
2. Missing key for any language falls back to EN.
3. `t("btn_snooze", "ru")` returns `"⏰ +10 мин"`.
4. Date formatting: `"Feb 18"` (en), `"18.02"` (ru), `"18/02"` (es).

Estimate: 1 day

---

## Epic C - Dispatcher Engine (`P0`)

### C1. Add `dispatch_scheduled_actions` Taskiq cron

1. Register in `src/core/tasks/scheduled_action_tasks.py`.
2. Cron: `* * * * *` (every minute).
3. Query due actions with `FOR UPDATE SKIP LOCKED`.
4. Batch limit: 50 per run.
5. Gate by `ff_scheduled_actions`.

Acceptance:

1. Cron runs every minute and processes due actions.
2. Does not process when `ff_scheduled_actions=False`.

Estimate: 1 day

### C2. Implement idempotent run executor

1. Use transactional fetch + lock (`SKIP LOCKED`).
2. Create run record before processing (unique constraint prevents duplicates).
3. Handle `IntegrityError` on duplicate run gracefully (skip, log).
4. Pre-send checks: quiet hours, comm_mode, end conditions.

Acceptance:

1. No duplicate sends in concurrency test.
2. `IntegrityError` caught and logged, not raised.
3. Skipped runs create record with `status='skipped'`.

Estimate: 2 days

### C3. Retry and failure policy

1. Exponential backoff: 1min, 5min, 15min between retries.
2. Pause action after `failure_count >= max_failures`.
3. Notify user when action auto-paused due to failures.

Acceptance:

1. Failures increment counters and state transitions are logged.
2. Auto-pause notification sent in user's language.
3. User can resume paused action via `manage_scheduled_action`.

Estimate: 1 day

---

## Epic D - Data Collection and Formatting (`P0`)

### D1. Create collector wrapper module

1. Create `src/core/scheduled_actions/collectors.py`.
2. Import collectors from `src/orchestrators/brief/nodes.py`.
3. Add thin wrapper that builds `BriefState` from `scheduled_actions` row fields.
4. Only invoke collectors matching `action.sources` list.
5. Track per-source status (success/fail/duration_ms).

Acceptance:

1. Brief orchestrator code NOT modified — zero regression risk.
2. Wrapper correctly maps `scheduled_action` fields to `BriefState`.
3. Per-source status captured in `sources_status` JSONB.
4. Timeout on individual collector does not block others.

Estimate: 1 day

### D2. Implement formatter modes

1. `compact` mode: Jinja2 template with i18n string injection, zero LLM calls.
2. `decision_ready` mode: LLM synthesis with system prompt per Tech Design §3.6.
3. Degraded mode: skip empty sections, add trust footer for failed sources.

Acceptance:

1. Output uses Telegram HTML only.
2. Compact mode produces valid HTML without any LLM call.
3. Decision-ready gated by `ff_sia_synthesis`.
4. Degraded mode clearly marks unavailable sources with `⚠️` footer.

Estimate: 1.5 days

### D3. Multi-model fallback chain

1. Primary synthesis: `claude-sonnet-4-6`.
2. Fallback: `gpt-5.2`.
3. Cheap fallback: `gemini-3-flash-preview`.
4. Each step catches provider errors and falls through.

Acceptance:

1. Tests verify fallback path on injected provider failure.
2. `model_used` field recorded in run log.
3. `fallback_used` dimension emitted for observability.

Estimate: 1 day

### D4. Message builder and button assembly

1. Create `src/core/scheduled_actions/message_builder.py`.
2. Build HTML message from formatter output + section headers + greeting.
3. Assemble inline keyboard with i18n button labels.
4. Send via `TelegramGateway` (not `send_telegram_message`) to support buttons.
5. Handle message splitting for >4000 chars (buttons on last chunk).

Acceptance:

1. Message renders correctly in Telegram with bold, bullets, emoji.
2. Buttons display in 2-column layout.
3. Button labels match user's language.
4. Messages >4000 chars split correctly, buttons on last chunk.

Estimate: 1 day

---

## Epic E - Telegram Interaction (`P0`)

### E1. Add `sched:*` callbacks to router

1. Add `sched:` prefix handling to `_handle_callback()`.
2. Parse sub-action: `snooze`, `pause`, `resume`, `run`, `del`.
3. Validate ownership (action.user_id + family_id match callback sender).
4. Route to appropriate handler function.
5. Return i18n response message.

Acceptance:

1. `snooze`, `pause`, `resume`, `run`, `del` all return deterministic i18n responses.
2. Ownership validation rejects forged action_ids.
3. After callback, original message buttons removed/updated.

Estimate: 1 day

### E2. Inline action buttons in scheduled messages

1. Build button list from i18n strings based on action status.
2. Active actions: `[Snooze] [Run now] [Pause]`.
3. Paused actions (if manually triggered): `[Resume]`.
4. Respect channel constraints (Telegram only).

Acceptance:

1. Buttons render correctly via Telegram gateway.
2. Callbacks execute and return correct response.
3. Button text matches user's language.

Estimate: 0.5 day

---

## Epic F - Market Parity Enhancements (`P1`)

### F1. Weekdays schedule support

1. Add `weekdays` to `ScheduleKind` enum.
2. `_compute_next_run()` skips Sat/Sun in user's timezone.
3. DST-safe behavior (preserves wall-clock).

Acceptance:

1. Mon-Fri trigger in user timezone with DST-safe behavior.
2. Parametrized tests for US/Eastern, Europe/Moscow.
3. i18n schedule description: "weekdays at 8:00" / "по будням в 8:00" / "días laborables a las 8:00".

Estimate: 1 day

### F2. Custom cron schedule support

1. Add `cron` to `ScheduleKind` enum.
2. Validate cron expression (reject dangerous patterns like `* * * * *` = every minute).
3. Use `croniter` library for next-run computation.
4. On invalid cron, return clarification question.

Acceptance:

1. Valid cron expressions compute correct `next_run_at`.
2. Invalid cron gets user-friendly clarification in their language.
3. Minimum interval enforced (not more frequent than every 5 minutes).

Estimate: 1.5 days

### F3. End conditions (`end_at`, `max_runs`)

1. Check end conditions in dispatcher pre-send phase.
2. `run_count >= max_runs` → set `status='completed'`, `next_run_at=NULL`.
3. `now >= end_at` → set `status='completed'`, `next_run_at=NULL`.
4. Notify user when action auto-completes.

Acceptance:

1. Action auto-completes and no longer dispatches once condition reached.
2. Completion notification sent in user's language.
3. Completed actions visible in list with ✅ icon.

Estimate: 1 day

### F4. Natural-language edit flow

1. Detect edit intent in `manage_scheduled_action` skill.
2. Match existing action by title or context.
3. Apply delta: change time, frequency, sources.
4. Recompute `next_run_at`.

Acceptance:

1. "Move my morning brief to 8:30" updates existing action without recreation.
2. "Add email to my daily summary" appends source.
3. Confirmation shows before/after in user's language.

Estimate: 1.5 days

---

## Epic G - Differentiators (`P2`)

### G1. Decision-ready output mode

1. Enhanced LLM synthesis prompt with priority ranking.
2. Top priority section at the beginning.
3. Recommended next action at the end.

Acceptance:

1. Message includes top priorities + one recommended next action.
2. Priority determination is context-aware (deadlines, amounts, urgency).
3. Output in user's language.

Estimate: 1 day

### G2. Finance-aware overlay

1. When `money_summary` source enabled, add budget risk indicators.
2. Visual indicators: 🟡 >80% budget, 🔴 >100% budget, 📈/📉 trend.
3. Budget progress bar: `█████░░░░░ 52%`.

Acceptance:

1. Budget/risk snippets appear when finance source is enabled and data available.
2. Progress bar renders correctly in Telegram HTML.

Estimate: 1 day

### G3. Outcome-based reminders

1. New `action_kind='outcome'` with `completion_condition` in config.
2. Schedule stays active until user taps "Done" callback.
3. Each run checks if condition is met (e.g., task completed, invoice paid).
4. Auto-complete when condition detected.

Acceptance:

1. "Until done" mode keeps schedule active until explicit completion callback.
2. "Done" button added to outcome-based messages.
3. Auto-detection works for task completion and invoice payment.

Estimate: 1.5 days

### G4. Trust footer (freshness/source status)

1. Show data freshness timestamp.
2. Show source availability: `📡 4/5 sources`.
3. Mark failed sources with name.

Acceptance:

1. Each message includes source freshness and missing-source markers.
2. Footer uses `<i>` italic for visual distinction.

Estimate: 0.5 day

---

## Epic H - Observability and Operations (`P0/P1`)

### H1. Add metrics, logs, and Langfuse traces

1. Structured log events per Tech Design §3.10.
2. Langfuse traces for synthesis calls.
3. Track all 5 PRD success metrics.
4. Per-run dimensions: model_used, tokens, duration, sources_status.

Acceptance:

1. Dashboard queries can compute activation, reliability, freshness, engagement, cost.
2. Langfuse traces visible for synthesis runs.

Estimate: 1 day

### H2. Add cleanup/retention for run logs

1. Daily cron (04:00): delete `scheduled_action_runs` older than 90 days.
2. Preserve runs for active/paused actions (only delete for completed/deleted).

Acceptance:

1. Old run logs pruned by policy without deleting active action state.
2. Cron registered in `scheduled_action_tasks.py`.

Estimate: 0.5 day

### H3. Runbook + alerts

1. Document actions for: high failure rate, send failures, queue lag, duplicate sends.
2. Alert thresholds: >5% duplicate sends, >10% failure rate, >5min dispatcher lag.

Acceptance:

1. Documented actions for each scenario.
2. Alert queries ready for monitoring system.

Estimate: 0.5 day

### H4. Security audit and RLS tests

1. Test: User A cannot list/manage User B's actions.
2. Test: Callback with forged action_id returns error.
3. Test: Dispatcher filters by user_id + family_id.
4. Test: Disabled/deleted users' actions not processed.

Acceptance:

1. All 4 security tests pass.
2. No data leaks across family boundaries.

Estimate: 0.5 day

---

## 4. Sprint Proposal

### Sprint 1 (P0 core) — ~10.5 days

1. A1, A2, A3, A4 — Data foundation + integration wiring
2. B1, B2, B5 — Intent, create skill, i18n

### Sprint 2 (P0 completion) — ~11 days

1. B3, B4 — List and manage skills
2. C1, C2, C3 — Dispatcher, idempotency, retries
3. D1, D4 — Collector wrappers, message builder
4. E1, E2 — Callbacks, buttons

### Sprint 3 (P0 formatting + P1) — ~8 days

1. D2, D3 — Formatter modes, fallback chain
2. H1, H4 — Observability, security audit
3. F1, F2 — Weekdays, cron

### Sprint 4 (P1 completion + P2) — ~7 days

1. F3, F4 — End conditions, NL edit
2. G1, G2, G3, G4 — Differentiators
3. H2, H3 — Cleanup, runbook

**Total: ~36.5 person-days (~7.3 weeks)**

Note: estimates include tests, i18n coverage, and integration for each item.

## 5. Definition of Done

1. Unit + integration tests implemented and passing.
2. `ruff check` passes.
3. Backward compatibility validated for existing reminder and brief flows.
4. Rollout behind feature flags (`ff_scheduled_actions`, `ff_sia_synthesis`) with staged activation plan.
5. Production telemetry and rollback steps documented.
6. All user-facing messages support EN/RU/ES.
7. Security tests pass (ownership validation, RLS isolation).
8. DST transition tests pass for major timezones.
9. Message formatting verified in Telegram (HTML rendering, buttons, emoji).
