# Scheduled Intelligence Actions (SIA)

**Author:** Codex  
**Date:** 2026-03-03  
**Status:** Draft  
**Star Rating:** 6.5 stars -> 7.5 stars (from static reminders to scheduled, decision-ready, cross-domain actions)  
**RICE Score:** 41.3 (Reach 75% x Impact 2.5 x Confidence 88% / Effort 4.0 wks)

---

## 1. Problem Statement

### What problem are we solving?

The project already supports task reminders and separately supports rich data synthesis (morning brief).  
But users cannot reliably schedule one request such as:

1. "At 8:00 AM, collect my calendar, tasks, money, and important emails."
2. "Send one short actionable summary."
3. "Let me snooze/reschedule from buttons."

Current reminders mostly send static stored text at trigger time. For users, this feels like a timer, not an AI assistant.

### Why this matters now

1. Market baseline in 2026 already includes scheduled AI actions and recurring automation.
2. We already have most building blocks in code (Taskiq cron, notification dispatch, brief collectors, callbacks, locale/timezone resolver).
3. Converging reminders + scheduled data actions provides immediate product lift without rewriting core architecture.

### Current architecture constraints (as-is)

1. Reminder creation and reminder dispatch are task-centric (`tasks.reminder_at`), not action-centric.
2. Rich data collection exists in `morning_brief` flow but is not reusable by reminder runtime.
3. Callback infrastructure exists, but reminder-specific post-actions (snooze/reschedule/run-now) are not implemented.
4. Runtime model policy is distributed (agents/skills/clients), while `ModelRouter` is mostly not in active runtime path.

---

## 2. Solution Overview

### What are we building?

A new capability class: **Scheduled Intelligence Actions**.

Each action has:

1. A schedule (`once`, `daily`, `weekly`, `monthly`, then `weekdays`/`cron` in next phase).
2. A data source set (`schedule`, `tasks`, `money_summary`, `email_highlights`, `outstanding`).
3. An output mode (`compact` or `decision_ready`).
4. Runtime execution that collects fresh data, synthesizes, sends, and logs run status.

### Example conversations

**Maria (household):**
```
Maria: Every weekday at 7:30 send me today's plan with calendar, tasks, and money.
Bot: Done. I will send a weekday brief at 7:30 in your timezone.

[07:30]
Bot: <b>Good morning</b>
- 2 meetings today
- 3 open tasks (1 urgent)
- Spending this month: $1,420
What should I prioritize first?
[Snooze 10m] [Run now] [Pause]
```

**David (service business):**
```
David: Every day at 8 check overdue invoices and today's jobs, then message me.
Bot: Scheduled daily at 8:00. I will include jobs + outstanding payments.
```

### What are we NOT building?

1. Autonomous purchasing or payment execution.
2. New communication channels in this phase (Telegram only).
3. Full geofencing/location triggers in this phase.
4. Unconfirmed destructive actions without approval.

---

## 3. User Stories

### P0 - Must Have

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | schedule a recurring AI action in natural language | I get useful updates without asking every day |
| 2 | User | choose what data to include (calendar/tasks/money/email) | the summary matches my workflow |
| 3 | User | receive actionable output with buttons | I can react quickly (snooze/pause/run now) |
| 4 | User | list/pause/resume/delete my scheduled actions | I stay in control |

### P1 - Should Have

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | use weekdays and custom cron schedules | I can match real routines |
| 2 | User | set end conditions (until date / N runs) | schedules don't run forever |
| 3 | User | edit existing schedule via natural language | I don't recreate from scratch |

### P2 - Nice to Have (Differentiators)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | get a decision-ready summary (priorities + next step) | I can act immediately |
| 2 | User | get finance-aware reminders | reminders reflect real budget risk |
| 3 | User | run outcome-based reminders ("until done") | I close loops instead of reading alerts |

### Won't Have (this cycle)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Auto-pay / auto-buy | trust/liability risk |
| 2 | Location triggers | requires separate geofencing system |
| 3 | Cross-channel delivery orchestration | out of scope for first release |

---

## 4. Success Metrics

| Category | Metric | Target | Measurement |
|----------|--------|--------|-------------|
| Activation | Users creating >=1 scheduled action in 30 days | >=35% active users | `scheduled_actions` create events |
| Reliability | Successful run delivery rate | >=98.5% | run logs + send success |
| Freshness | Sections with data <=15 min old at send time | >=95% | run metadata timestamps |
| Engagement | Messages with any action (reply/button) in 2h | >=30% | callback/reply correlation |
| Retention | Week-4 retention uplift for SIA users | +8% vs control | cohort analysis |
| Cost | Incremental cost per SIA active user | <=$1.5/month | usage logs by model |

### Failure signals

1. >5% duplicate sends for same schedule slot.
2. >20% users pausing all actions within first week.
3. >10% runs failing due to source unavailability for 3+ consecutive days.

---

## 5. Technical Scope

### New product intents/skills

1. `schedule_action` (create/update from NL).
2. `list_scheduled_actions`.
3. `manage_scheduled_action` (pause/resume/delete/reschedule).

### Runtime architecture

1. New scheduled-action model and run log model.
2. New cron dispatcher (`* * * * *`) with idempotent run handling.
3. Reusable data collectors (from brief path) as shared module.
4. Formatter with two modes:
   1. Fast template mode (no LLM).
   2. LLM synthesis mode with fallback chain.
5. Telegram callback actions for post-send controls.

### Model policy (allowed model set only)

1. Extraction/structure: `gpt-5.2`.
2. Synthesis primary: `claude-sonnet-4-6`.
3. Synthesis fallback: `gpt-5.2`.
4. Cheap fallback summary: `gemini-3-flash-preview`.
5. Keep existing intent-detection stack: `gemini-3-flash-preview` + `claude-haiku-4-5` fallback.

---

## 6. Proactivity/Dispatch Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| `next_run_at <= now` | Execute scheduled action pipeline | every minute scan | Telegram |
| Callback `snooze` | Shift `next_run_at` | on demand | Telegram |
| Callback `pause/resume` | Update status | on demand | Telegram |
| Callback `run_now` | Immediate one-off run | on demand | Telegram |

### Guardrails

1. Per-user cap for proactive sends/day.
2. Honor communication mode and suppression settings.
3. Degraded-mode message when some sources fail.
4. Retry with exponential backoff before marking run failed.

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Duplicate sends under multi-worker race | Medium | High | `FOR UPDATE SKIP LOCKED`, idempotency key `(action_id, planned_run_at)` |
| LLM cost spikes | Medium | Medium | fast template mode first, synthesis fallback chain, max token caps |
| Source outages (calendar/email) | High | Medium | partial-data rendering + source status footer |
| User notification fatigue | Medium | High | caps, quiet hours, easy pause/snooze |
| Schedule parsing ambiguity | Medium | Medium | clarify loop + explicit confirmation text |

---

## 8. Timeline

| Phase | Scope | Duration |
|-------|-------|----------|
| Phase 1 | schema + dispatcher + create/list/manage skills | 1.5 weeks |
| Phase 2 | shared collectors + formatter + callbacks | 1.0 week |
| Phase 3 | parity features (`weekdays`, `cron`, end conditions) | 1.0 week |
| Phase 4 | differentiators + hardening + rollout | 0.5 week |

---

## 9. Release Criteria

1. `ruff check` and full test suite pass.
2. No duplicate send in load test scenario.
3. P0 user stories validated by QA checklist.
4. Feature flags allow progressive rollout (5%, 25%, 100%).
