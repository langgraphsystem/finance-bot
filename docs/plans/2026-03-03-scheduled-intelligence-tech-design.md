# Technical Design: Scheduled Intelligence Actions (SIA)

Date: 2026-03-03  
Owner: Core Platform

## 1. Goals

1. Add a first-class scheduled action pipeline (not only `tasks.reminder_at`).
2. Reuse existing architecture: DomainRouter, skills, Taskiq, notification dispatch, callback handling.
3. Keep backward compatibility with current reminders and morning brief.

## 2. As-Is Architecture Snapshot

### 2.1 What exists and is reusable

1. Reminder skill and due-reminder cron:
   1. `src/skills/set_reminder/handler.py`
   2. `src/core/tasks/reminder_tasks.py`
2. Brief data collection + synthesis:
   1. `src/skills/morning_brief/handler.py`
   2. `src/orchestrators/brief/nodes.py`
3. Worker/scheduler runtime:
   1. `src/core/tasks/broker.py`
   2. `scripts/entrypoint.sh`
4. Unified Telegram dispatch helpers:
   1. `src/core/notifications_pkg/dispatch.py`
5. Callback pipeline and pending actions:
   1. `src/core/router.py`
   2. `src/core/pending_actions.py`
6. Multi-model SDK + tool support:
   1. `src/core/llm/clients.py`

### 2.2 Constraints

1. Existing reminder flow is task-centric and message text is mostly static.
2. `ModelRouter` is not the active runtime policy entrypoint.
3. Existing cron tasks are module-specific (reminder/life/proactivity), so SIA must avoid duplicating collector logic again.

## 3. Target Architecture

## 3.1 New Modules

1. `src/core/models/scheduled_action.py`
2. `src/core/models/scheduled_action_run.py`
3. `src/core/scheduled_actions/engine.py`
4. `src/core/scheduled_actions/collectors.py`
5. `src/core/scheduled_actions/formatter.py`
6. `src/core/tasks/scheduled_action_tasks.py`
7. `src/skills/schedule_action/handler.py`
8. `src/skills/list_scheduled_actions/handler.py`
9. `src/skills/manage_scheduled_action/handler.py`

## 3.2 Database Design

### `scheduled_actions`

1. `id UUID PK`
2. `family_id UUID FK families`
3. `user_id UUID FK users`
4. `title VARCHAR(255) NOT NULL`
5. `instruction TEXT NOT NULL`
6. `action_kind VARCHAR(32) NOT NULL`
7. `schedule_kind VARCHAR(16) NOT NULL`
8. `schedule_config JSONB NOT NULL`
9. `sources JSONB NOT NULL`
10. `output_mode VARCHAR(32) NOT NULL DEFAULT 'compact'`
11. `timezone VARCHAR(50) NOT NULL`
12. `language VARCHAR(10) NOT NULL`
13. `status VARCHAR(16) NOT NULL DEFAULT 'active'`
14. `next_run_at TIMESTAMPTZ`
15. `last_run_at TIMESTAMPTZ`
16. `last_success_at TIMESTAMPTZ`
17. `failure_count INTEGER NOT NULL DEFAULT 0`
18. `max_failures INTEGER NOT NULL DEFAULT 3`
19. `created_at TIMESTAMPTZ DEFAULT now()`
20. `updated_at TIMESTAMPTZ DEFAULT now()`

Indexes:

1. `(status, next_run_at)`
2. `(family_id, user_id, status)`

### `scheduled_action_runs`

1. `id UUID PK`
2. `scheduled_action_id UUID FK scheduled_actions`
3. `planned_run_at TIMESTAMPTZ NOT NULL`
4. `started_at TIMESTAMPTZ`
5. `finished_at TIMESTAMPTZ`
6. `status VARCHAR(16) NOT NULL`
7. `error_code VARCHAR(64)`
8. `error_text TEXT`
9. `payload_snapshot JSONB`
10. `message_preview TEXT`
11. `created_at TIMESTAMPTZ DEFAULT now()`

Unique constraint:

1. `(scheduled_action_id, planned_run_at)` for idempotency.

## 3.3 Runtime Pipeline

1. Dispatcher cron (`every minute`) fetches due actions:
   1. `status='active'`
   2. `next_run_at <= now()`
   3. `FOR UPDATE SKIP LOCKED`
2. Engine creates run row (idempotent by unique key).
3. Collectors run in parallel with timeouts:
   1. `schedule`
   2. `tasks`
   3. `money_summary`
   4. `email_highlights`
   5. `outstanding`
4. Formatter chooses rendering mode:
   1. Fast template mode if simple payload.
   2. LLM synthesis mode if complex/multi-source.
5. Send via `send_telegram_message`.
6. Update run status and action state:
   1. success -> reset `failure_count`, set `last_success_at`, compute `next_run_at`
   2. failure -> increment `failure_count`, retry/backoff, pause when threshold exceeded

## 3.4 Schedule Resolution

Supported P0:

1. `once`: fixed datetime.
2. `daily`: same local wall-clock time.
3. `weekly`: same weekday/time.
4. `monthly`: same day/time, clamp short month.

Supported P1:

1. `weekdays`: Mon-Fri by local timezone.
2. `cron`: validated cron expression.
3. End conditions: `end_at`, `max_runs`.

Implementation notes:

1. Store raw schedule params in `schedule_config`.
2. Compute `next_run_at` in UTC, preserve local wall-clock semantics.
3. Reuse DST-safe strategy from recurring reminders (`original_reminder_time` concept).

## 3.5 Callbacks and Interaction Contracts

Add callback actions in router:

1. `sched:snooze:<action_id>:<minutes>`
2. `sched:pause:<action_id>`
3. `sched:resume:<action_id>`
4. `sched:run_now:<action_id>`
5. `sched:delete:<action_id>`

Response button contract (Telegram):

1. `Snooze 10m`
2. `Run now`
3. `Pause` or `Resume`

## 3.6 Model and Prompt Policy

Allowed model IDs only:

1. `gpt-5.2`
2. `claude-sonnet-4-6`
3. `claude-haiku-4-5`
4. `gemini-3-flash-preview`
5. `gemini-3.1-pro-preview` (optional future)

Model assignment:

1. Extraction from conversation context: `gpt-5.2` JSON mode.
2. Main synthesis: `claude-sonnet-4-6`.
3. Fallback synthesis: `gpt-5.2`.
4. Cheap emergency fallback: `gemini-3-flash-preview`.

## 3.7 Observability

Add structured logs and metrics:

1. `scheduled_action_triggered`
2. `scheduled_action_run_succeeded`
3. `scheduled_action_run_failed`
4. `scheduled_action_partial_data`
5. `scheduled_action_callback_used`

Dimensions:

1. `user_id`, `family_id`
2. `action_kind`, `schedule_kind`
3. `language`, `timezone`
4. `model_used`, `fallback_used`
5. `duration_ms`

## 3.8 Security and Isolation

1. Keep existing family isolation via RLS context (`set_family_context` in router path; worker uses scoped queries by family/user).
2. Validate callback ownership (action belongs to current user/family).
3. Do not execute side-effect actions without explicit callback/approval.

## 4. Integration Points

1. `src/core/intent.py`
   1. add intent guidance for `schedule_action` and manage/list variants.
2. `src/core/schemas/intent.py`
   1. add fields for schedule config and sources.
3. `src/agents/config.py`
   1. include new intents in tasks agent.
4. `src/core/domains.py`
   1. map new intents to `Domain.tasks` (or new `Domain.automation` in future).
5. `src/skills/__init__.py`
   1. register new skills.
6. `scripts/entrypoint.sh`
   1. include `src.core.tasks.scheduled_action_tasks` in task modules.

## 5. Rollout Plan

1. Flag off by default in production: `ff_scheduled_actions=False`.
2. Internal enablement for test users.
3. Beta rollout:
   1. 5% users
   2. 25% users
   3. 100%
4. Rollback path:
   1. disable flag
   2. no impact on existing `set_reminder` and existing cron tasks.

## 6. Test Strategy

1. Unit tests:
   1. schedule parser and `next_run_at` calculations
   2. collector timeout/failure behavior
   3. formatter output for compact and decision-ready modes
2. Integration tests:
   1. create action -> due dispatch -> send -> next run progression
   2. callback actions (`snooze/pause/resume/run_now`)
   3. idempotency (duplicate trigger protection)
3. Regression tests:
   1. existing `set_reminder` behavior unchanged
   2. existing `dispatch_due_reminders` unaffected

## 7. Open Decisions

1. Keep new intent in `Domain.tasks` vs introducing `Domain.automation`.
2. Introduce email channel delivery in P1 or keep Telegram-only longer.
3. Whether to route synthesis through LangGraph node stack or keep direct engine + `generate_text`.

