# Email Management: Gmail Integration via Conversation

**Author:** AI Assistant
**Date:** 2026-02-17
**Status:** Draft
**Star Rating:** 4★ → 6★ (from "no email capability" to "reads, summarizes, drafts, and sends email with user approval")
**RICE Score:** 15.2 (Reach 65% x Impact 2.0 x Confidence 70% / Effort 6 wks)

---

## 1. Problem Statement

### What problem are we solving?

Email is the #1 source of task anxiety for both consumers and small business owners. The average US adult receives 120+ emails per day. Checking email requires context-switching to a separate app, scanning a cluttered inbox, deciding what matters, and composing replies — each step pulling the user away from what they were actually doing. 65% of target users check email 10+ times per day, spending 30+ minutes total on what should be a 5-minute task. The bot should handle the inbox the way a human assistant would: filter what matters, summarize it, draft replies, and only bother the user with decisions.

### The Maria Test

> Maria has 47 unread emails. 40 are promotions, 3 are from Emma's school, 2 are from her doctor, 1 is a reply from a parent about a playdate, and 1 is a utility bill notice. She spends 10 minutes scrolling through spam to find the 7 that matter. She texts back 2 of them and forgets about the doctor's office until tomorrow. She needed to say "check my email" and get: "You have 7 emails that matter — 3 from school (picture day Friday, field trip permission, early dismissal), 1 playdate confirm from Lisa, 1 from Dr. Park's office about next month's appointment, 1 utility bill due Feb 25. Want me to reply to any?"

### The David Test

> David gets a quote request from a potential client. He's on a job site and can't open Gmail on his phone without getting his phone dirty. The email sits unanswered for 3 hours. The client finds another plumber. David needed to say "check my email" and hear "You got a quote request from Mrs. Rodriguez for a bathroom remodel at 22 Pine St. Want me to send your standard estimate response?" — then just approve and move on.

### Who else has this problem?

65% of target users. Email is a universal pain point that worsens with age and business growth. It's the gateway to professional communication. People who can't manage email from the same interface where they manage tasks and calendar lose the "single assistant" benefit. Email Management is RICE 15.2 — lower priority than calendar due to higher effort (OAuth + complex parsing + send approval flow), but critical for the Phase 2 "can't live without" goal.

---

## 2. Solution Overview

### What are we building?

Five skills that read, summarize, reply to, follow up on, and send emails — all via Gmail API through natural conversation. The bot acts as an email filter and assistant: it reads the inbox, highlights what matters, drafts replies, and sends with explicit user approval. A LangGraph orchestrator handles the multi-step drafting flow (plan → read → write → review → send) because email composition involves revision loops and quality checks before a side-effect (sending).

### Conversation Example

**Maria's scenario:**
```
Maria: check my email
Bot: 7 new emails that matter:
1. Emma's school — picture day is Friday, wear blue
2. Emma's school — field trip permission slip (needs reply)
3. Emma's school — early dismissal Wednesday at 1pm
4. Lisa Johnson — playdate Saturday confirmed
5. Dr. Park — appointment reminder for March 10
6. ConEd — bill due Feb 25, $142.30
7. Noah's swim coach — practice moved to 5pm Thursday

Need me to reply to any of these?

Maria: reply to the field trip one, say Emma has permission and I can chaperone
Bot: Draft reply:

"Hi, Emma has my permission for the field trip. I'm also available to chaperone if you still need volunteers. — Maria"

Send this?

Maria: yes
Bot: Sent. ✓
```

**David's scenario:**
```
David: anything important in my email?
Bot: 3 emails need attention:
1. Mrs. Rodriguez — requesting a quote for bathroom remodel at 22 Pine St
2. Home Depot — your supply order shipped, arriving Thursday
3. Mike — forwarded photos from the Elm St job for your review

The rest is newsletters and promotions. Want me to handle any of these?

David: send Mrs. Rodriguez my standard estimate response, I can come Tuesday at 10am
Bot: Draft to Mrs. Rodriguez:

"Hi Mrs. Rodriguez, thanks for reaching out. I'd be happy to give you an estimate for the bathroom remodel. I can come by 22 Pine St this Tuesday at 10:00 AM to take a look. Does that work for you? — David, D&D Plumbing"

Send this?

David: send it
Bot: Sent. ✓ Also added "Estimate — Mrs. Rodriguez, 22 Pine St" to your calendar for Tuesday 10am.
```

### What are we NOT building?

1. Full email client (folder management, labels, archiving) — bot is an assistant, not a replacement for Gmail
2. Attachment handling (reading PDFs, downloading files) — complex, low initial demand
3. Email template library — users describe what to say, bot drafts it fresh
4. Multi-provider support (Outlook, Yahoo) — Gmail first via Google OAuth, expand later
5. Auto-reply without user approval — every sent email requires explicit "send it" confirmation
6. Email marketing or bulk sending — personal/business communication only

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | say "check my email" and see a summary of important messages | I don't scroll through 100+ emails to find the 5 that matter |
| 2 | User | say "reply to [email]" and have the bot draft a response | I compose replies in seconds, not minutes |
| 3 | User | review and approve before the bot sends anything | I never send an email I haven't seen |
| 4 | User | ask "summarize the thread with [person]" | I get up to speed on a conversation without reading 20 messages |
| 5 | User | say "email [person] about [topic]" to compose a new email | I send emails without opening Gmail |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | ask "any emails I haven't replied to?" | I don't forget to respond to important messages |
| 2 | User | say "make it shorter" or "more formal" after seeing a draft | I iterate on drafts without re-explaining |
| 3 | User | get notified about urgent emails within minutes | time-sensitive messages don't sit unread |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | set rules like "always summarize emails from school" | the bot learns my preferences for different senders |
| 2 | User | forward an email to the bot and say "handle this" | I delegate email tasks naturally |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Auto-reply without confirmation | Sending email on someone's behalf without approval is a trust violation |
| 2 | Attachment reading/processing | Separate skill (scan_document exists for images); PDF parsing adds complexity |
| 3 | Folder/label management | Bot is an assistant, not a full email client |
| 4 | Outlook/Yahoo support | Single provider first. 70%+ of target users use Gmail. |
| 5 | Email marketing/bulk features | Personal and business communication only |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who connect Gmail within 14 days | > 30% | OAuth completion events |
| **Usage** | Email interactions per connected user per week | > 3 | Aggregate on intent logs (read_inbox + send_email + draft_reply) |
| **Quality** | % of drafts approved on first try (no revision) | > 50% | Track revision requests within same thread |
| **Safety** | % of emails sent without user approval | 0% | Audit log check — hard fail if > 0% |
| **Retention** | % of email-connected users still using email skills in week 3 | > 40% | Cohort analysis |

### Leading Indicators (check at 48 hours)

- [ ] Users who check inbox once come back to check it again the same day
- [ ] At least 1 in 3 inbox checks results in a follow-up action (reply, compose, summarize)

### Failure Signals (trigger re-evaluation)

- [ ] > 50% of users start OAuth but don't complete (flow too confusing)
- [ ] > 40% of drafts need 2+ revisions (tone/content miss)
- [ ] Users send 0 emails through the bot after 1 week (trust barrier too high)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | LangGraph StateGraph: planner → reader → writer → reviewer → sender |
| **Skills** | 5 new: `read_inbox`, `send_email`, `draft_reply`, `follow_up_email`, `summarize_thread` |
| **APIs** | Gmail API via `aiogoogle` (shared OAuth with Calendar) |
| **Models** | Claude Haiku 4.5 (read_inbox, follow_up, summarize), Claude Sonnet 4.5 (send_email, draft_reply — quality matters) |
| **Database** | `email_cache` (existing from Phase 1 migration), `oauth_tokens` (shared with Calendar) |
| **Background Jobs** | `sync_gmail_inbox` — every 10 min, check for new important emails |

### LangGraph Orchestrator

```
planner → decides which nodes to invoke based on intent
    ↓
reader → fetches email(s) from Gmail API, parses, summarizes
    ↓
writer → drafts reply/new email using Claude Sonnet
    ↓
reviewer → checks quality, tone, completeness
    ↓ (loop back to writer if revision needed, max 2 revisions)
sender → shows draft to user, waits for "send it" approval, then sends via Gmail API
```

Email is the only calendar/email domain that needs LangGraph because:
- Revision loops ("make it shorter", "more formal") require state persistence
- Quality review before side-effect (sending) is critical — can't unsend an email
- Multi-step flows (read thread → compose reply → review → send) need graph routing

### Data Model

OAuth tokens table (shared with Calendar):

```sql
-- Same oauth_tokens table from Calendar PRD
-- Provider: 'google', Scopes: includes 'gmail.modify' + 'calendar'
```

Email cache (already created in Phase 1 migration):

```sql
-- Already exists: email_cache table
-- gmail_id, thread_id, from_email, subject, snippet, is_read, is_important, followup_needed
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User hasn't connected Gmail | "I'll need access to your email. Here's a link to connect your Google account: [deep link]" (same OAuth flow as Calendar — grants both scopes at once) |
| Inbox has 0 important emails | "Inbox is clean — nothing needs your attention right now." |
| User says "send it" for a draft that's > 5 min old | Re-confirm: "Still want to send this to [recipient]? [show draft summary]" |
| Gmail API rate limit (250 quota units/second) | Queue requests, retry with backoff. User sees brief "checking..." delay. |
| User asks to reply to an email that no longer exists | "I can't find that email anymore — it may have been deleted. Want me to compose a new message instead?" |
| Very long email thread (50+ messages) | Summarize last 10 messages, note: "This is a long thread (50+ messages). I summarized the recent ones. Want the full summary?" |
| User requests revision after approval | "That email was already sent. Want me to send a follow-up?" |
| Sensitive content in email (medical, legal) | Process normally — bot doesn't judge content. If guardrails trigger on the user's outgoing text, block and explain. |
| First-time user with no Gmail connected | Works partially — bot explains what email features are available and prompts OAuth connection. Research/writing/tasks skills work without Gmail. |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Claude Haiku (read, follow-up, summarize) | ~$0.001 | $150 (150K queries) |
| Claude Sonnet (send, draft_reply — quality) | ~$0.005 | $250 (50K queries) |
| Gmail API | $0 | $0 (free for per-user OAuth) |
| Background sync (10-min cron) | ~$0.0005 | $75 (150K sync ops) |
| **Total** | | **~$1.90/user** |

Within $3-8/month budget. Combined with Calendar ($1.40), total Phase 2 API cost: ~$3.30/user.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| New important email detected (background sync) | Notify user: "[sender]: [subject] — want me to summarize?" | Max 3/day | User's primary channel |
| Email unanswered > 24h from an important sender | Nudge: "You haven't replied to [sender]'s email from yesterday. Want me to draft a reply?" | Max 1/day | User's primary channel |
| Morning brief (combined with Calendar) | Include email summary: "3 emails need attention today" | 1x/day (shared with Calendar) | User's primary channel |

### Rules

- Proactive email notifications only for emails the bot classifies as "important" (not spam, not promotions, from known contacts or new senders with actionable content).
- Max 3 email notifications per day. Users can say "stop email notifications" to disable.
- Follow-up nudges only for emails from contacts in the user's address book or previous correspondents.
- Morning brief email summary is part of the Calendar morning brief — not a separate message.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Google OAuth app review rejection for Gmail scope | Medium | High | Gmail scopes require additional review. Apply early, prepare privacy policy and data usage documentation. Fallback: start with read-only scope, add send later. |
| User sends wrong email through the bot (trust failure) | Low | Critical | Mandatory preview + explicit "send" confirmation. Draft expires after 10 min — requires re-confirmation. Clear "cancel" path at every step. |
| Email parsing errors (complex HTML, non-English) | Medium | Medium | Use Gmail API snippet for summaries (pre-parsed). For full body, strip HTML and use Gemini Flash for content extraction. |
| Privacy concern — bot reads all email | Medium | Medium | Clear permission model: bot only reads emails the user asks about, plus background sync for importance scoring (metadata only, not full body). Users can revoke access anytime. |
| Background sync cost at scale | Low | Medium | Sync metadata only (sender, subject, snippet). Full body fetched on-demand. Sync frequency configurable per user. |
| LangGraph orchestrator adds latency | Low | Low | Most email flows complete in 2-3 nodes. Writer→reviewer loop is max 2 iterations. Total latency ~3-5 seconds for a compose flow. |

### Dependencies

- [ ] Google Cloud project with Gmail API enabled (new — requires separate enablement)
- [ ] OAuth consent screen configured for `gmail.modify` scope (new — requires Google app review)
- [ ] `aiogoogle` package (shared dependency with Calendar)
- [ ] `cryptography` package (shared dependency with Calendar)
- [ ] `langgraph` package (new dependency for email orchestrator)
- [ ] Phase 1 `email_cache` table exists (done — migration 005)
- [ ] Calendar module OAuth flow (shared infra — build Calendar first)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD (this document) | 0.5 day | PRD approved |
| Infra | LangGraph orchestrator scaffolding + email state | 1 day | Orchestrator graph compiles and runs with mock nodes |
| Build P0 | 5 skills + agent + orchestrator nodes | 2 days | Inbox reading and email sending work end-to-end |
| Approval | Send approval flow with confirmation UI | 0.5 day | "Send this?" → "Sent ✓" flow works |
| Proactivity | Background sync + importance scoring + notifications | 1 day | New email alerts and follow-up nudges |
| Polish | Edge cases, HTML parsing, long threads | 1 day | Production ready |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted | Justification |
|-----------|--------|-------------|----------|---------------|
| Problem Clarity | 2.0x | 5 | 10.0 | Universal pain — 120 emails/day, 30 min wasted. Maria's school emails and David's lost client are vivid, daily scenarios. |
| User Stories | 1.5x | 4 | 6.0 | Clear P0/P1/P2. Won't Have has 5 items. Deducted 1: "revision loop" UX for P1 is undefined — needs design before build. |
| Success Metrics | 1.5x | 4 | 6.0 | Metrics include a hard 0% safety target (no unauthorized sends). Deducted 1: "important email" classification accuracy is hard to measure without labeled data. |
| Scope Definition | 1.0x | 4 | 4.0 | Clear exclusions. Deducted 1: LangGraph orchestrator adds significant scope vs. simple skills — could be split into two phases. |
| Technical Feasibility | 1.0x | 3 | 3.0 | OAuth review for Gmail is a real blocker. LangGraph is a new dependency. Deducted 2: Gmail scope review can take 4-6 weeks and may be rejected. |
| Risk Assessment | 1.0x | 4 | 4.0 | Critical risk (wrong email sent) has strong mitigation. Gmail review risk acknowledged. Deducted 1: no Plan B if Gmail scope is denied. |
| **Total** | **8.0x** | | **33.0/40** |

**Normalized: (33.0 / 40) x 30 = 24.8/30**

| Score | Verdict | Action |
|-------|---------|--------|
| **24.8** | **Almost there** | Address Gmail scope review risk, then proceed |

### Action items before build:
1. Submit Google OAuth verification request immediately — don't wait for PRD implementation
2. Define Plan B: read-only Gmail scope (no send) as fallback if `gmail.modify` is rejected
3. Design the revision loop UX for draft editing (P1 but impacts orchestrator design)

---

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (has 5)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (3 defined)
- [x] Cost estimate is within $3-8/month per user ($1.90 email + $1.40 calendar = $3.30 combined)
- [x] Star rating is stated and justified (4★ → 6★)
- [x] RICE score matches PRIORITIZATION.md (15.2)
- [x] Proactivity section defines frequency limits (max 3 notifications/day, follow-up nudge max 1/day)
- [x] Edge cases include "no history" cold-start scenario (Gmail not connected → OAuth prompt)
