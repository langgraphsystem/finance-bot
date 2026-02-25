# Finance Bot: Architecture Audit (As-Is) + vNext Plan

Date: 2026-02-25
Updated: 2026-02-25
Scope: Full project architecture snapshot + target architecture and rollout plan for `language + timezone + reminder dispatch` without breaking the current flow.

## Progress Tracker

| Phase | Status | Commits |
|-------|--------|---------|
| Phase 0: Safety and Observability | **DONE** | `a7bd9c8`, `3a5d43c` |
| Phase 1: Data Preparation | **DONE** | `fa9bb40` (migration + backfill) |
| Phase 2: Central Resolver | **PARTIAL** | `57c6260`, `57222cf`, `2fa5594` (read path for reminders/life, not proactivity) |
| Phase 3: Write Path Normalization | NOT STARTED | |
| Phase 4: Dispatch Unification | NOT STARTED | |
| Phase 5: Hardening and Cleanup | NOT STARTED | |

## 1. Executive Summary

The current system is a working multi-channel assistant with FastAPI webhooks, Taskiq background jobs, modular skills, and domain/agent routing. Core business features are available and actively wired.

The main reliability issue for reminders and proactive notifications is not one bug, but a consistency gap:

1. Language source is split between `users.language` and `user_profiles.preferred_language`.
2. Timezone can be auto-overwritten from Telegram `language_code` mapping.
3. Notification dispatch logic is split across multiple tasks with partially duplicated locale/time handling.

This creates user-visible mismatch:

1. English account receiving Russian labels (`Напоминание`).
2. Morning notifications sent at night due to incorrect timezone assignment.
3. Inconsistent locale behavior across reminder/proactivity/life notifications.

## 2. Audit Method

Inspection was performed directly on runtime wiring, API entrypoints, routers, task schedulers, skills registry, and integration modules.

Primary files inspected:

1. `api/main.py`, `api/miniapp.py`, `api/oauth.py`, `api/browser_extension.py`
2. `src/core/router.py`, `src/core/intent.py`, `src/core/domain_router.py`, `src/core/domains.py`
3. `src/agents/config.py`, `src/agents/base.py`
4. `src/core/tasks/*.py`, `src/proactivity/*.py`
5. `src/skills/__init__.py` and reminder/life/monitor-related skills
6. `src/core/models/*`, `src/core/family.py`, `src/core/db.py`, `src/core/config.py`
7. `Procfile`, `scripts/entrypoint.sh`

## 3. Current Architecture (As-Is)

### 3.1 Runtime Topology

1. Web process:
   1. FastAPI app with Telegram/Slack/WhatsApp/SMS/Stripe webhooks.
   2. Mini App REST API and static web assets.
2. Worker process:
   1. Taskiq worker for cron and async jobs.
   2. Separate scheduler in worker mode (`scripts/entrypoint.sh`).
3. Storage:
   1. PostgreSQL (SQLAlchemy async).
   2. Redis (rate limit, onboarding state, dedup keys, task/job state).

### 3.2 Request Flow (Messages)

1. Incoming channel message.
2. User/family context resolution.
3. Guardrails.
4. Intent detection (single-stage, v2 scaffold exists but inactive).
5. DomainRouter -> AgentRouter -> Skill execution.
6. Persistence (conversation memory + DB records).
7. Outgoing message via channel gateway.

### 3.3 Background Flow (Notifications)

1. Reminder dispatch (`dispatch_due_reminders`) every minute.
2. Morning/evening prompts every 15 minutes with local-time window check.
3. Proactivity trigger evaluation every 10 minutes.
4. Weekly digest, profile learning, recurring payments, and anomaly jobs.

## 4. What Is Included in Architecture Today

### 4.1 Included and Wired

1. Multi-channel gateways: Telegram, Slack, WhatsApp, SMS.
2. Mini App CRUD for finance/tasks/life entities.
3. Skills registry with broad domain coverage:
   1. Finance tracking and analytics.
   2. Life tracking.
   3. Tasks/reminders/shopping list.
   4. Research/writing.
   5. Email/calendar via Google (Composio).
   6. Browser actions and booking/CRM flows.
4. Domain routing + orchestrators:
   1. Email orchestrator (for compose flows).
   2. Brief orchestrator (morning/evening aggregate summaries).
5. Proactivity engine for data triggers:
   1. Deadline warning.
   2. Budget alert.
   3. Overdue recurring payment.

### 4.2 Present but Partial / Not Fully Wired

1. Subscription lifecycle:
   1. Stripe webhook updates exist.
   2. Full checkout/portal/cancel user flow is not wired as public API product flow.
2. Usage logging module exists but is not integrated in the main LLM execution path.
3. `ModelRouter` exists but is not used as runtime model selection entrypoint.
4. `detect_intent_v2` exists but is not active.
5. Voice call subsystem files exist, but inbound voice webhook/ws routes are not mounted in `api/main.py`.
6. Monitor entities (`price_alert`, `news_monitor`) are created, but monitor checks are not part of active proactivity trigger set.
7. `notification_tasks.daily_notifications` currently does not directly deliver outbound messages in worker context.
8. Some brief/evening sections remain placeholders (`invoices_sent`).

## 5. Root-Cause Analysis: language + timezone + reminder dispatch

### 5.1 Language Mismatch

Current reminder notification language is selected by:

1. `coalesce(UserProfile.preferred_language, User.language)` in worker tasks.
2. Reminder label map chooses `en/es/zh/ru` based on normalized language.

Why mismatch happens:

1. `users.language` default is `ru` in model.
2. `user_profiles.preferred_language` default is `en`.
3. Historic rows can contain inconsistent values across these two fields.
4. Different flows read/update different fields (onboarding, settings, background jobs).

Result: some users with English onboarding context still resolve as Russian in reminder worker.

### 5.2 Timezone Mismatch

Current timezone behavior:

1. `user_profiles.timezone` default is `America/New_York`.
2. There is auto-setting by Telegram `language_code` when timezone is still default.
3. If language code is `ru`, timezone may be auto-set to `Europe/Moscow`.

Why “morning at night” happens:

1. Morning task checks local window around `08:00` based on stored timezone.
2. If timezone was inferred from language rather than actual location, send window is wrong for user real location.
3. Fallback to `UTC` for invalid/missing timezone can also shift delivery time.

### 5.3 Dispatch Logic Fragmentation

Reminder-related texts and scheduling are distributed across:

1. `reminder_tasks.py` (due reminders).
2. `life_tasks.py` (morning/evening prompts).
3. `proactivity_tasks.py` + `proactivity/engine.py` (trigger notifications).

Each module has its own locale/time normalization path. This increases drift risk and inconsistent user experience.

## 6. Target Architecture vNext (Focused on Locale and Reminder Reliability)

### 6.1 Design Goals

1. Single source of truth for user locale/timezone preferences.
2. Deterministic reminder timing in user local time.
3. Uniform message localization across all notification channels/tasks.
4. Backward-compatible rollout with feature flags and safe fallback.

### 6.2 vNext Components

1. `UserLocaleService` (new core service):
   1. Resolves `language_for_notifications`.
   2. Resolves `timezone_for_scheduling`.
   3. Applies explicit precedence rules.
2. `TimezoneResolutionPolicy`:
   1. Explicit user choice > city/IP/geolocation > channel metadata > default.
   2. Never derive timezone from language by default.
3. `NotificationTemplateService`:
   1. Centralized i18n keys/templates for reminder/morning/evening/proactivity.
   2. Reused by all worker tasks.
4. `ReminderDispatchCoordinator`:
   1. Shared helper for due reminders and proactive windows.
   2. Uniform dedup/idempotency key strategy.
5. `LocaleAuditTelemetry`:
   1. Structured logs for resolved locale/timezone source.
   2. Metrics for mismatch and off-window sends.

### 6.3 Data Model vNext (Minimal Additions)

Add fields in `user_profiles`:

1. `notification_language` (nullable, explicit user override).
2. `timezone_source` (enum/string: `user_set`, `geo_ip`, `city_geocode`, `channel_hint`, `default`).
3. `timezone_confidence` (0-100).
4. `locale_updated_at` (timestamp).

Keep existing fields for compatibility:

1. `preferred_language`.
2. `timezone`.
3. `users.language`.

## 7. Concrete Plan (No-Break Rollout)

### Phase 0: Safety and Observability (No behavior change)

1. Add feature flags:
   1. `FF_LOCALE_V2_READ`
   2. `FF_LOCALE_V2_WRITE`
   3. `FF_REMINDER_DISPATCH_V2`
2. Add structured logs in worker tasks:
   1. `user_id`, `resolved_language`, `resolved_timezone`, `source`.
3. Add dashboards/counters:
   1. Reminder sends by language.
   2. Morning send hour histogram by user timezone.
   3. Invalid timezone fallback count.

Files:

1. `src/core/tasks/reminder_tasks.py`
2. `src/core/tasks/life_tasks.py`
3. `src/core/tasks/proactivity_tasks.py`

### Phase 1: Data Preparation (Backward-compatible migration)

1. Alembic migration for new `user_profiles` columns.
2. Backfill script:
   1. If `notification_language` is null -> derive from `preferred_language` then `users.language`.
   2. Set `timezone_source='default'` for existing rows unless known from geo path.

Files:

1. `alembic/versions/*_locale_timezone_v2.py`
2. `scripts/backfill_locale_timezone_v2.py`

### Phase 2: Central Resolver (Read path only)

1. Implement `src/core/locale/service.py`:
   1. `resolve_language(user, profile)`
   2. `resolve_timezone(user, profile)`
2. Integrate resolver under `FF_LOCALE_V2_READ` in:
   1. Reminder worker.
   2. Life tasks.
   3. Proactivity send path.

Files:

1. `src/core/locale/service.py` (new)
2. `src/core/tasks/reminder_tasks.py`
3. `src/core/tasks/life_tasks.py`
4. `src/core/tasks/proactivity_tasks.py`
5. `src/proactivity/engine.py` (if needed for localization handoff)

### Phase 3: Write Path Normalization

1. Onboarding/settings flows write both:
   1. `preferred_language`
   2. `notification_language` (if explicit language selection).
2. Replace “language -> timezone” auto-mapping with safer policy:
   1. Keep as optional low-confidence hint only.
   2. Do not overwrite existing user-set timezone.
3. Prefer city/geo detect to propose timezone updates with confidence.

Files:

1. `api/main.py` (`_maybe_set_timezone_from_language` behavior change)
2. `api/miniapp.py` (`/settings`, `/geo/detect`)
3. `src/skills/onboarding/handler.py`
4. `src/core/family.py`

### Phase 4: Dispatch Unification

1. Extract shared notification text/template helpers.
2. Use single helper for normalization + message building in all notification tasks.
3. Standardize send window checks and dedupe key format.

Files:

1. `src/core/notifications/` (new package, e.g. `locale.py`, `templates.py`, `dispatch.py`)
2. `src/core/tasks/reminder_tasks.py`
3. `src/core/tasks/life_tasks.py`
4. `src/core/tasks/proactivity_tasks.py`

### Phase 5: Hardening and Cleanup

1. Add admin/diagnostic command for a user:
   1. Show effective language/timezone and source.
2. Remove deprecated fallback paths after stable rollout.
3. Lock defaults:
   1. Consider changing `users.language` default from `ru` to `en` or environment-driven default for new installs.

## 8. Test Plan (Required to Prevent Regressions)

### 8.1 Unit Tests

1. Locale resolver precedence matrix (all combinations).
2. Timezone resolver with invalid/missing values.
3. Reminder label localization across languages.

Suggested test files:

1. `tests/test_core/test_locale_service.py` (new)
2. `tests/test_core/test_reminder_dispatch.py` (extend)
3. `tests/test_core/test_life_tasks.py` (extend)

### 8.2 Integration Tests

1. End-to-end reminder creation -> dispatch with user timezone.
2. Morning prompt local window correctness across 3 timezones.
3. English account never receiving Russian reminder label unless explicit override.

### 8.3 Migration Tests

1. Backfill correctness for existing users with mixed language fields.
2. No null/invalid `notification_language` after migration.

## 9. Rollout and Rollback Strategy

### Rollout

1. Deploy Phase 0 + 1 with flags off.
2. Enable `FF_LOCALE_V2_READ` for internal test cohort (1-5%).
3. Enable `FF_LOCALE_V2_WRITE` after read-path stability.
4. Enable `FF_REMINDER_DISPATCH_V2` progressively by cohort.

### Rollback

1. Toggle off flags instantly to revert to old behavior.
2. Keep schema additions (non-breaking).
3. Keep telemetry to analyze failed cohorts before next attempt.

## 10. Immediate Quick-Fix Recommendation (Before Full vNext)

If an immediate hotfix is needed before full architecture migration:

1. Stop timezone overwrite by language code for existing users unless explicit consent.
2. In reminder/life tasks, prefer `preferred_language` only if explicitly set, else use `users.language`.
3. Add warning log when resolved timezone differs from user recent geo/city hints.

This can reduce wrong-language and wrong-time sends quickly while full vNext is implemented.

