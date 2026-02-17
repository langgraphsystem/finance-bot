# Tasks & Reminders: Core Task Management

**Author:** AI Assistant
**Date:** 2026-02-17
**Status:** In Development
**Star Rating:** 5★ → 6★ (brings task management from nonexistent to proactive with reminders and deadline tracking)
**RICE Score:** 64.1 (Reach 95% x Impact 3.0 x Confidence 90% / Effort 4 wks)

---

## 1. Problem Statement

### What problem are we solving?

Users text the bot about tasks ("remind me to pick up Emma at 3:15", "add to my list: call dentist") and get routed to `general_chat` because no task intents exist. The bot has a `tasks` table in the database (Phase 1 migration) but zero skills to use it. Every competitor (Apple Reminders, Google Tasks, Todoist) handles this. Users who try to set reminders and fail churn within 48 hours.

### The Maria Test

> Maria texts "remind me to pick up Emma at 3:15" and the bot says something generic about helping with finances. She wanted a one-tap reminder that pings her at 3:15. Instead she opens Apple Reminders — a separate app she has to remember to check. This happens 3-4 times per day: doctor appointments, grocery pickup, school events.

### The David Test

> David texts "add task: follow up with Mrs. Chen about the invoice" and the bot doesn't understand. He pulls out a sticky note and writes it down. By Friday, the sticky note is lost under paperwork. Mrs. Chen's $850 invoice goes unpaid for another week. David needs tasks that live in the same chat where he manages everything else.

### Who else has this problem?

95% of target users need task management (RICE table). Tasks & Reminders is the #1 RICE-scored module (64.1) after Onboarding. The US market expects any AI assistant to handle "remind me" and "add to my list" from day one.

---

## 2. Solution Overview

### What are we building?

Four skills that create, list, complete, and remind users about tasks — all via natural language in the same chat. Tasks are stored in the existing `tasks` table with priorities, deadlines, and completion tracking.

### Conversation Example

**Maria's scenario:**
```
Maria: remind me to pick up emma at 3:15
Bot: Got it — reminder set for 3:15 PM today: pick up Emma.

Maria: also add "buy Noah's soccer cleats" to my list
Bot: Added: buy Noah's soccer cleats. You have 4 open tasks.

Maria: what's on my list?
Bot: Your tasks:
1. Pick up Emma — today 3:15 PM
2. Buy Noah's soccer cleats
3. Call dentist for Emma's checkup
4. Grocery order for Saturday

Maria: done with the dentist call
Bot: Marked done: call dentist for Emma's checkup. 3 tasks left.
```

**David's scenario:**
```
David: task: follow up with mrs chen about invoice, high priority
Bot: Added: follow up with Mrs. Chen about invoice (high priority).

David: what do I need to do today?
Bot: Your tasks (4 open):
1. [urgent] Quote for Oak Ave bathroom — due today
2. [high] Follow up with Mrs. Chen about invoice
3. Mike's schedule for next week
4. Order PVC fittings

David: done with oak ave quote
Bot: Marked done: quote for Oak Ave bathroom. 3 tasks left.
```

### What are we NOT building?

1. Recurring tasks — Phase 2 (requires Taskiq cron integration for repeating schedules)
2. Task delegation to contacts — Phase 2 (requires contacts skill to be built first)
3. Subtasks / checklists — Phase 2 (adds complexity without core value)
4. Calendar integration — separate Calendar module (Phase 2, requires Google OAuth)
5. Push notifications for reminders — Phase 2 (requires Taskiq cron + Telegram push)

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | create a task via text | I don't need a separate app for my to-do list |
| 2 | User | list my open tasks | I see everything I need to do in one place |
| 3 | User | mark a task as done | I track my progress without switching apps |
| 4 | User | set a reminder with a time | I get pinged at the right moment |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | set priority on a task | I focus on what matters most |
| 2 | User | set a deadline without a specific time | I see overdue tasks in my list |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | see tasks grouped by priority | I scan my list faster |
| 2 | User | assign a task to a contact | I delegate work via chat |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Recurring tasks | Requires Taskiq cron scheduling — Phase 2 |
| 2 | Subtasks / checklists | Over-engineering for MVP. Simple flat list first. |
| 3 | Task categories / projects | Users should describe tasks naturally. Auto-categorization comes later. |
| 4 | Gamification / streaks | ICE score 45 (Won't Have) per PRIORITIZATION.md |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of new users who create a task within 24h | > 40% | Count `create_task` intents per new user |
| **Usage** | Tasks created per active user per week | > 3 | Aggregate query on `tasks` table |
| **Completion** | % of tasks marked done within 7 days | > 50% | `completed_at - created_at` analysis |
| **Retention** | % of task users active in week 2 | > 60% | Cohort analysis |

### Leading Indicators (check at 48 hours)

- [ ] Users create tasks on first try (no "I don't understand" responses)
- [ ] `list_tasks` intent fires at least 1x per user per day

### Failure Signals (trigger re-evaluation)

- [ ] < 20% of users create a task in first week (problem: intent detection not catching natural language)
- [ ] > 40% of tasks never completed and no new tasks created (problem: users try once and abandon)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None — tasks are linear CRUD, routed via AgentRouter |
| **Skills** | 4 new: `create_task`, `list_tasks`, `set_reminder`, `complete_task` |
| **APIs** | None external |
| **Models** | Claude Haiku 4.5 for all task skills (fast, cheap, sufficient for CRUD) |
| **Database** | Existing `tasks` table (Phase 1 migration 005) |
| **Background Jobs** | None in P0. P1 adds reminder cron via Taskiq. |

### Data Model

```sql
-- Already exists from migration 005
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    family_id UUID REFERENCES families(id),
    user_id UUID REFERENCES users(id),
    title VARCHAR(500),
    description TEXT,
    status task_status DEFAULT 'pending',     -- pending, in_progress, done, cancelled
    priority task_priority DEFAULT 'medium',  -- low, medium, high, urgent
    due_at TIMESTAMPTZ,
    reminder_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    assigned_to UUID REFERENCES contacts(id),
    domain VARCHAR(50),
    source_message_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User creates task with empty text | Bot asks "What task do you want to add?" |
| User says "done" without specifying which task | Bot shows numbered list and asks which one |
| User says "done with dentist" and multiple tasks match | Bot picks the closest match by title similarity |
| User has zero tasks and asks to list | Bot says "No open tasks. Text me to add one." |
| User sets reminder without a time | Bot creates task without reminder, confirms deadline only |
| Ambiguous priority ("important") | Map to "high". Only "urgent" requires explicit "urgent" keyword. |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| LLM calls | $0 (no LLM calls — pure DB operations) | $0 |
| Storage | ~$0.001 per task | $0.50 (500 tasks/user avg) |
| **Total** | **~$0** | **$0.50** |

Within $3-8/month budget.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Task has `reminder_at` and time arrives | Send reminder message | Per task | Current chat |
| Task has `due_at` and deadline is today | Include in morning brief | 1x/day | Morning brief |
| Tasks overdue > 24h | Nudge: "You have 2 overdue tasks" | 1x/day max | Current chat |

### Rules

- Max 5 proactive task messages per day (reminders + nudges combined).
- User can say "stop reminding me about X" — sets `reminder_at = NULL` for that task.
- Reminder proactivity requires Phase 2 (Taskiq cron). P0 stores `reminder_at` but doesn't fire notifications.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Intent detection confuses "task" life events with new task skills | Medium | Medium | Add priority rules: "add task:", "remind me", "to-do" → task skills; "план дня" stays as day_plan |
| Users expect push notifications for reminders in P0 | Medium | Low | Bot confirms "reminder saved" and notes "I'll include it in your daily summary" (no push yet) |
| Task title matching for "complete_task" is too fuzzy | Low | Medium | Use case-insensitive substring match. If multiple matches, ask user to pick. |
| Russian/English language mix in task titles | Low | Low | Store titles as-is. Search is case-insensitive and works on both languages. |

### Dependencies

- [x] Phase 1 Core Generalization (tasks table, domain router, enums)
- [ ] Phase 2: Taskiq cron for reminder notifications (P1 feature)
- [ ] Phase 2: Contacts module for task delegation (P2 feature)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD | 0.5 day | PRD approved (this document) |
| Build P0 | 4 skills + agent + intents + tests | 1 day | All tests pass, skills functional |
| Build P1 | Priority display, deadline nudges | 0.5 day | Enhanced list formatting |
| Polish | Edge cases, language matching | 0.5 day | Production ready |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted | Justification |
|-----------|--------|-------------|----------|---------------|
| Problem Clarity | 2.0x | 5 | 10.0 | Problem is specific, universal (95% reach), validated by RICE 64.1. Maria and David scenarios are vivid and tied to real daily friction. |
| User Stories | 1.5x | 4 | 6.0 | Clear P0/P1/P2 differentiation. Won't Have has 4 items. Stories are testable via conversation. Deducted 1 for no delegation story in P0. |
| Success Metrics | 1.5x | 4 | 6.0 | Metrics are specific and measurable. Failure signals defined. Deducted 1 because completion rate target (50%) is a guess without baseline data. |
| Scope Definition | 1.0x | 5 | 5.0 | Tight scope: 4 skills, no external deps, no recurring tasks. "Not building" list is clear. |
| Technical Feasibility | 1.0x | 5 | 5.0 | Uses existing table, existing patterns, zero new dependencies. Cost is near-zero. |
| Risk Assessment | 1.0x | 4 | 4.0 | Key risks identified. Intent confusion mitigation is concrete. Deducted 1 because fuzzy matching strategy needs testing. |
| **Total** | **8.0x** | | **36.0/40** |

**Normalized: (36.0 / 40) x 30 = 27.0/30**

| Score | Verdict | Action |
|-------|---------|--------|
| **27.0** | **Ready to build** | Proceed to implementation |

---

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (has 4)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (2 defined)
- [x] Cost estimate is within $3-8/month per user ($0.50)
- [x] Star rating is stated and justified (5★ → 6★)
- [x] RICE score matches PRIORITIZATION.md (64.1)
- [x] Proactivity section defines frequency limits (max 5/day)
- [x] Edge cases include "no history" cold-start scenario (zero tasks → "No open tasks")
