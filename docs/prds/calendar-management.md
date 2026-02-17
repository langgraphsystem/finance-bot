# Calendar Management: Google Calendar Integration via Conversation

**Author:** AI Assistant
**Date:** 2026-02-17
**Status:** Draft
**Star Rating:** 4★ → 6★ (from "no calendar capability" to "proactive daily scheduling with conflict detection and morning briefs")
**RICE Score:** 30.6 (Reach 90% x Impact 2.0 x Confidence 85% / Effort 5 wks)

---

## 1. Problem Statement

### What problem are we solving?

Users manage their schedules across multiple apps — Google Calendar on desktop, Apple Calendar on phone, sticky notes on the fridge. Checking availability, creating events, and rescheduling requires opening a separate app, switching context, and manually typing details. 90% of target users check their calendar 3+ times daily. Every context switch costs 30-60 seconds and breaks the conversation flow with the bot.

### The Maria Test

> Maria is texting the bot about groceries when she remembers Emma has a dentist appointment she needs to reschedule. She switches to Google Calendar, scrolls to find the appointment, calls the dentist's office, agrees on a new time, goes back to Calendar, deletes the old event, creates a new one, then returns to the bot to finish her grocery list. This takes 5 minutes for a 30-second task. She needs to say "move Emma's dentist to Thursday at 2pm" and have it done.

### The David Test

> David is on a job site when a client calls to schedule an estimate. He can't open Google Calendar with wet hands, so he tells the client "I'll get back to you." He forgets. The client goes to another plumber. David needed to say "schedule an estimate for Mrs. Chen, Thursday 3pm at 45 Oak Ave" and have it show up in his calendar — no app switching, no forgetting.

### Who else has this problem?

90% of target users. Calendar is the most universal productivity tool after messaging. The inability to manage it from the same conversation where tasks and reminders live creates constant friction. Calendar Management is RICE 30.6, Phase 1 MVP #5 in the prioritization table.

---

## 2. Solution Overview

### What are we building?

Five skills that read, create, modify, and summarize calendar events — all via Google Calendar API through natural language. Users connect their Google account once (OAuth), then manage their calendar entirely through conversation. Morning briefs combine calendar + tasks for a complete daily overview. All operations use conflict detection before creating events.

### Conversation Example

**Maria's scenario:**
```
Maria: what's on my calendar tomorrow?
Bot: Tomorrow (Tuesday):
• 9:00 AM — Noah's swimming class
• 2:00 PM — Emma's dentist (Dr. Park)
• 4:30 PM — Grocery pickup at Costco

You're free 10am-2pm and after 5pm.

Maria: move the dentist to Thursday at 2pm
Bot: Moved Emma's dentist to Thursday 2pm. No conflicts — Thursday's clear after noon.

Maria: schedule a playdate at the Johnsons' Saturday 11am to 1pm
Bot: Created: Playdate at Johnsons' — Saturday 11am-1pm. Added to your calendar.
```

**David's scenario:**
```
David: am I free Thursday morning?
Bot: Thursday morning:
• 8:00 AM — Jose on the Oak Ave bathroom remodel
• You're free from 10am onward.

David: schedule an estimate for Mrs. Chen, Thursday 3pm at 45 Oak Ave
Bot: Created: Estimate — Mrs. Chen, 45 Oak Ave — Thursday 3pm. I set it for 1 hour. That work?

David: what's my day look like tomorrow?
Bot: Morning, David. Tomorrow:
• 8:00 AM — Jose: Oak Ave remodel (day 3)
• 10:00 AM — Mike: Elm St pipe repair
• 2:00 PM — Mike: Oak Ave follow-up
• 3 tasks due: order PEX fittings, send Mrs. Rodriguez quote, call supplier

No conflicts. Mike has a 4-hour gap between jobs — want to add something?
```

### What are we NOT building?

1. Apple Calendar integration — Apple has no public API; defer indefinitely
2. Multi-calendar sync (Google + Outlook) — single provider first, expand in P2
3. Automatic attendee invites — requires email integration (Email module dependency)
4. Recurring event creation — Google Calendar API supports it but adds complexity; P1
5. Calendar sharing between family members — requires multi-user OAuth; P2
6. Travel time estimation between events — requires location API; P2

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | see my schedule for today/tomorrow/this week | I know what's coming without opening Calendar |
| 2 | User | create a calendar event via text | I add events without switching apps |
| 3 | User | find my free slots | I know when I'm available for new commitments |
| 4 | User | reschedule an event | I move things around without opening Calendar |
| 5 | User | get a morning brief with calendar + tasks | I start the day knowing everything that's on my plate |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | create recurring events | weekly meetings and regular activities are handled |
| 2 | User | get conflict warnings before creating events | I don't double-book myself |
| 3 | User | delete/cancel an event | I clean up my calendar from the chat |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | share availability with someone | I coordinate meetings without back-and-forth |
| 2 | User | see travel time between events | I know if I can make it between appointments |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Apple Calendar integration | No public API — Apple doesn't allow third-party calendar access |
| 2 | Outlook / Exchange support | Single provider (Google) first. Expand later based on user demand. |
| 3 | Automatic meeting scheduling with external people | Requires Calendly-like infrastructure — separate product |
| 4 | Video call integration (Zoom/Meet links) | Requires Zoom/Google Meet API; adds scope without core value |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who connect Google Calendar within 7 days | > 40% | OAuth completion events |
| **Usage** | Calendar queries per connected user per week | > 5 | Aggregate on intent logs |
| **Quality** | % of events created successfully without user correction | > 85% | Track correction/reschedule within 5 min |
| **Retention** | % of connected users who use calendar skills in week 2 | > 60% | Cohort analysis |
| **Morning brief** | % of connected users who read their morning brief | > 50% | Message delivery + response rate |

### Leading Indicators (check at 48 hours)

- [ ] Users who connect OAuth create at least 1 event within the first session
- [ ] Morning brief generates a follow-up action (user responds with a task or change)

### Failure Signals (trigger re-evaluation)

- [ ] > 30% of users start OAuth flow but don't complete it (friction in the flow)
- [ ] > 20% of created events need immediate correction (parsing failure)
- [ ] Users check calendar once but don't return (feature isn't sticky)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None — calendar operations are linear CRUD, no revision loops needed |
| **Skills** | 5 new: `list_events`, `create_event`, `find_free_slots`, `reschedule_event`, `morning_brief` |
| **APIs** | Google Calendar API via `aiogoogle` (new dependency) |
| **Models** | Claude Haiku 4.5 (all calendar skills — fast, mechanical tasks) |
| **Database** | `calendar_cache` (existing from Phase 1 migration), `oauth_tokens` (new) |
| **Background Jobs** | `sync_calendar_events` — every 15 min, sync upcoming events to local cache |

### Data Model

OAuth tokens table (shared with Email module):

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    family_id UUID NOT NULL REFERENCES families(id),
    provider TEXT NOT NULL DEFAULT 'google',
    access_token_encrypted BYTEA NOT NULL,
    refresh_token_encrypted BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    scopes JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

Calendar cache (already created in Phase 1 migration `005_multi_domain_tables.py`):

```sql
-- Already exists: calendar_cache table
-- google_event_id, title, start_at, end_at, attendees (JSONB), prep_notes
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User hasn't connected Google Calendar | Bot says: "I'll need access to your calendar first. Here's a link to connect your Google account: [deep link]" |
| OAuth token expired | Auto-refresh via aiogoogle. If refresh fails, ask user to reconnect. |
| User asks about a date with no events | "You're free all day [date]. Want to schedule something?" |
| Conflicting event on creation | "You already have [existing event] at that time. Want me to schedule around it or reschedule the conflict?" |
| Ambiguous event reference ("move the meeting") | "Which one? You have 3 meetings tomorrow: [list]. Which one should I move?" |
| Google API rate limit | Queue requests, retry with backoff. User sees: "Hang on, talking to Google..." |
| User in different timezone than default | Use `user_profiles.timezone` (default America/New_York). Parse relative dates accordingly. |
| Morning brief with zero events | "No events today — your calendar is clear. Any tasks you want to focus on?" |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Claude Haiku (all 5 skills) | ~$0.001 | $300 (300K queries) |
| Google Calendar API | $0 | $0 (free for per-user OAuth) |
| aiogoogle token refresh | $0 | $0 (no LLM cost) |
| Background sync (15-min cron) | ~$0.0005 | $50 (100K sync ops) |
| **Total** | | **~$1.40/user** |

Within $3-8/month budget.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Morning (user's preferred time, default 7:30 AM) | Send morning brief with today's events + tasks due | 1x/day | User's primary channel |
| 30 min before event | Send event reminder with context | Per event, max 5/day | User's primary channel |
| Conflict detected on background sync | Alert user about overlapping events | When detected, max 2/day | User's primary channel |

### Rules

- Morning brief is opt-in: activated after user uses calendar skills 3+ times. User can say "stop morning briefs" to disable.
- Event reminders only for events created or modified through the bot (don't spam for pre-existing Google events).
- Max 5 proactive messages per day across all calendar triggers.
- Every proactive message is actionable — user can respond "skip", "reschedule", or "details".

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Google OAuth app review delay | Medium | High | Apply for verification early. Use restricted scopes. Have test accounts for development. Unverified apps work for <100 users. |
| Users confused by OAuth flow (Telegram → browser → back) | Medium | Medium | Clear step-by-step message: "Tap the link, sign in with Google, tap Allow. You'll be redirected back." Add a "having trouble?" fallback. |
| Calendar parsing errors (ambiguous dates, timezone issues) | Medium | Medium | Use Claude Haiku for NL→structured date extraction. Confirm ambiguous dates: "Thursday Feb 20 at 3pm EST — correct?" Default to user's timezone. |
| Google Calendar API changes or deprecation | Low | High | Use stable v3 API. Pin aiogoogle version. Monitor Google deprecation notices. |
| Token encryption key compromise | Low | High | Use Fernet symmetric encryption with key from env var. Key rotation support from day one. Tokens stored encrypted at rest. |

### Dependencies

- [ ] Google Cloud project with Calendar API enabled (existing — used for Gemini)
- [ ] OAuth consent screen configured for `calendar` scope (new — requires setup)
- [ ] `aiogoogle` package added to `pyproject.toml` (new dependency)
- [ ] `cryptography` package for token encryption (new dependency)
- [ ] Phase 1 `calendar_cache` table exists (done — migration 005)
- [ ] Phase 1 `user_profiles` table with timezone (done — migration 005)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD (this document) | 0.5 day | PRD approved |
| Infra | Google OAuth flow + token storage + aiogoogle client | 1.5 days | OAuth works end-to-end |
| Build P0 | 5 skills + agent + intents + tests | 1.5 days | All tests pass, calendar CRUD works |
| Proactivity | Morning brief cron + event reminders | 1 day | Proactive messages sending |
| Polish | Edge cases, timezone handling, conflict detection | 0.5 day | Production ready |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted | Justification |
|-----------|--------|-------------|----------|---------------|
| Problem Clarity | 2.0x | 5 | 10.0 | Daily pain for 90% of users. Maria's 5-minute reschedule and David's lost client are real, frequent scenarios. |
| User Stories | 1.5x | 4 | 6.0 | Clear P0/P1/P2 with 4 Won't Have items. Deducted 1: recurring events are P1 but many users expect them from day one. |
| Success Metrics | 1.5x | 4 | 6.0 | Metrics are measurable with clear targets. 3 failure signals. Deducted 1: "morning brief engagement" is hard to measure precisely (read ≠ useful). |
| Scope Definition | 1.0x | 5 | 5.0 | Tight: 5 skills, CRUD only, no multi-provider. Clear exclusion of Apple Calendar, Zoom links, and auto-scheduling. |
| Technical Feasibility | 1.0x | 4 | 4.0 | Proven architecture (aiogoogle + OAuth). Deducted 1: OAuth flow through Telegram deep link is untested UX — needs validation. |
| Risk Assessment | 1.0x | 4 | 4.0 | Key risks covered with concrete mitigations. OAuth review and deep link UX are the biggest unknowns. Deducted 1: no fallback if Google OAuth is rejected. |
| **Total** | **8.0x** | | **35.0/40** |

**Normalized: (35.0 / 40) x 30 = 26.3/30**

| Score | Verdict | Action |
|-------|---------|--------|
| **26.3** | **Ready to build** | Proceed to implementation |

---

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (has 4)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (3 defined)
- [x] Cost estimate is within $3-8/month per user ($1.40)
- [x] Star rating is stated and justified (4★ → 6★)
- [x] RICE score matches PRIORITIZATION.md (30.6)
- [x] Proactivity section defines frequency limits (max 5/day, morning brief 1x/day)
- [x] Edge cases include "no history" cold-start scenario (OAuth not connected → deep link prompt)
