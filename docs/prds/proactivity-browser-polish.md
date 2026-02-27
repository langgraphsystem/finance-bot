# Proactivity + Browser Automation + Polish

**Author:** Claude
**Date:** 2026-02-19
**Status:** In Development
**Star Rating:** 6★ → 7★ — This phase takes the product from "proactive daily assistant" (6★ already achieved via morning_brief orchestrator) to "cross-domain intelligent assistant that acts on your behalf" (7★). Going to 8★ requires full autonomous delegation (book, pay, schedule without asking) — deferred.
**RICE Score:** Reach 70% × Impact 2.5 × Confidence 70% / Effort 5 wks = 24.5

---

## 1. Problem Statement

### What problem are we solving?

The bot only responds when the user sends a message. It doesn't warn about upcoming deadlines, expiring invoices, or price drops. Users miss important things because they forgot to ask. Additionally, when users need something done on a website (check a price, fill a form), they have to leave the chat and do it themselves.

### The Maria Test

> Maria forgets to follow up on Emma's dentist appointment because nobody reminded her. She also spends 20 minutes every week checking grocery prices across three store websites. She wants the bot to remind her about important things before they're urgent and check prices for her automatically.

### The David Test

> David loses $800/month because he forgets to follow up on unpaid invoices. He also wastes time checking supply prices at Home Depot and Ferguson Supply websites. He wants the bot to alert him about overdue invoices and monitor material prices for him.

### Who else has this problem?

Every user who relies on the bot daily. Proactive notifications are the #1 feature that separates "useful tool" from "can't live without" (the 5★ → 6★ → 7★ jump). Browser automation unlocks use cases that pure text chat can't solve.

---

## 2. Solution Overview

### What are we building?

1. **Proactivity engine** — evaluates triggers (time-based + data-based) without LLM, generates notifications only when a trigger fires. Extends existing Taskiq cron setup.
2. **Browser automation** — Browser-Use library + LangGraph orchestrator for multi-step web tasks (price checks, form filling, research).
3. **Monitor skills** — user-created monitors ("alert me when lumber prices drop below $5") backed by the existing `monitors` table.
4. **Action approval system** — inline confirmation for actions with side effects (send email, create event, execute web action).
5. **User profile auto-learning** — nightly task that updates `learned_patterns` from conversation history.

### Conversation Example

**Maria's scenario (proactive):**
```
[Bot, 7:30am, unprompted]
Bot: Morning! Today: Emma's dentist at 2pm — I'll remind you at 1:30.
Noah's soccer at 4pm. One thing: milk is $3.29 at Target
this week (was $4.19). Want me to add it to your list?

[Bot, 1:30pm, reminder]
Bot: Emma's dentist in 30 minutes. Traffic is light — about 12 min from your location.
```

**David's scenario (monitor + browser):**
```
David: monitor lumber prices at Home Depot, alert me if they drop below $5
Bot: Done — I'll check Home Depot daily and alert you when 2x4 lumber drops below $5/piece.

[Next day, 8am]
Bot: Lumber alert: 2x4 at Home Depot dropped to $4.79 (was $5.49). Want me to check Ferguson too?

David: check the price on a new Ridgid pipe wrench at homedepot.com
Bot: Checking Home Depot now...
Found: Ridgid 18" Aluminum Pipe Wrench — $42.97. Want me to add it to your supplies list?
```

### What are we NOT building?

1. **Autonomous purchasing** — Bot presents options, user decides. No auto-buy.
2. **Browser-based login to user accounts** — Only public web pages. No stored passwords.
3. **Voice calls** — Deferred. RICE score 0.4.
4. **Gamification / streaks** — Doesn't help Maria or David. ICE score 45.
5. **Real-time stock/crypto monitoring** — Regulatory issues. Price/news monitors only.

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | Get proactive deadline warnings | I don't miss important dates |
| 2 | User | Get budget alerts when spending exceeds my limit | I stay within budget |
| 3 | User | Ask the bot to check a price on a website | I don't have to open a browser |
| 4 | User | Confirm or reject actions before the bot executes them | I stay in control |
| 5 | User | Have the bot learn my preferences over time | I don't have to repeat myself |

### P1 — Should Have (within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | Create persistent monitors ("alert me when X") | I track prices and news passively |
| 2 | User | Get follow-up reminders for unanswered emails | Nothing falls through the cracks |
| 3 | User | Say "stop reminding me about X" | I control notification frequency |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | Have the bot fill out online forms for me | I save time on paperwork |
| 2 | User | Get competitor price comparisons | I find the best deals |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Auto-purchasing | Trust/liability issues — user must approve |
| 2 | Account login | Security risk — public pages only |
| 3 | Stock/crypto alerts | Regulatory compliance needed |
| 4 | Voice calls | RICE 0.4 — extremely hard, low reach |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who receive proactive notification in first 48h | > 80% | Proactivity engine logs |
| **Engagement** | Proactive messages responded to (vs ignored) | > 40% | Message correlation |
| **Retention** | 30-day retention for users with proactive features | > 55% | Cohort analysis |
| **Browser** | Web actions completed successfully | > 70% | BrowserTool result logs |
| **Monitors** | Active monitors per user (week 4) | > 0.5 | monitors table count |

### Leading Indicators (check at 48 hours)

- [ ] Proactivity engine fires triggers for > 90% of active users
- [ ] Browser tool completes a price check in < 30 seconds
- [ ] Profile auto-learning updates `learned_patterns` for users with > 10 messages

### Failure Signals (trigger re-evaluation)

- [ ] Users disable proactive notifications (> 20% opt out)
- [ ] Browser automation success rate < 50%
- [ ] Proactive messages generate negative feedback (> 5% "stop" requests)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Proactivity** | `src/proactivity/` — engine, triggers, evaluator, scheduler via Taskiq |
| **Browser** | `src/tools/browser.py` — Browser-Use wrapper. `src/orchestrators/browser/graph.py` — LangGraph |
| **Skills** | 4 new: web_action, price_check, price_alert, news_monitor |
| **Approval** | `src/core/approval.py` — inline keyboard confirmation for side-effect actions |
| **Auto-learning** | `src/core/tasks/profile_tasks.py` — nightly Taskiq cron |
| **Models** | `claude-sonnet-4-6` for browser, `claude-haiku-4-5` for monitors, `gemini-3-flash-preview` for profile learning |
| **Database** | Existing: `monitors`, `user_profiles.learned_patterns`. No new tables |

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Website blocks browser automation | Return "I couldn't access that page." Suggest alternative |
| Browser task times out (> 60s) | Cancel, return partial result if available |
| User has no tasks/calendar (cold start) | Skip proactive triggers that need data. Only fire after 3+ days of usage |
| User in "silent" communication mode | Skip all proactive messages except critical alerts (budget > 150%) |
| Two monitors fire at the same time | Batch into one message. Max 3 alerts per message |
| User says "stop reminding me about invoices" | Store suppression in `learned_patterns`. Respect permanently |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Proactivity checks (no-LLM evaluation) | $0 | $0 |
| Proactive message generation (when triggered) | $0.002 | $200 |
| Browser automation (Claude Sonnet) | $0.05 | $500 |
| Monitor checks (web scrape + Haiku) | $0.003 | $300 |
| Profile learning (nightly, Gemini Flash) | $0.001 | $30 |
| **Total** | | **~$1,030** |

Within $3-8/month per user budget ($1.03/user).

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| Morning (user's preferred hour) | Send morning brief | Daily | Primary channel |
| Task due in < 4 hours | Deadline warning | Once per task | Primary channel |
| Budget > 80% of monthly limit | Budget alert | Once per period | Primary channel |
| Email unanswered > 24h | Follow-up nudge | Once per email | Primary channel |
| Invoice unpaid > 7 days | Payment reminder | Every 3 days, max 3 | Primary channel |
| Monitor trigger fires | Alert message | Per monitor interval | Primary channel |
| Evening (user's preferred hour) | Evening recap | Daily | Primary channel |

### Rules

- Max 5 proactive messages per user per day across all triggers.
- "Silent" mode suppresses all except critical budget alerts.
- Every proactive message ends with an actionable option.
- User says "stop [X] reminders" → stored in `learned_patterns`, respected permanently.
- Triggers evaluated without LLM. LLM called only for message generation after a trigger fires.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Browser-Use unreliable on dynamic SPAs | Med | Med | Limit to known-good sites initially. Fallback to web_search for content extraction |
| Proactive messages annoy users | Med | High | Max 5/day cap. Easy opt-out. "Silent" mode. Track opt-out rate |
| Browser containers expensive at scale | Low | Med | Use Steel.dev only for complex tasks. Simple price checks use httpx + trafilatura |
| Profile auto-learning makes wrong inferences | Med | Low | Conservative updates. Only write to `learned_patterns` after 10+ consistent signals |
| LangGraph browser orchestrator adds latency | Low | Med | 60s hard timeout. Show "Working on it..." typing indicator |

### Dependencies

- [x] Taskiq + Redis (existing)
- [x] `monitors` table (migration 005)
- [x] `user_profiles.learned_patterns` column (migration 005)
- [ ] browser-use package (add to pyproject.toml)
- [ ] langchain-anthropic package (add to pyproject.toml)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| PRD | This document | 1 day | PRD approved |
| Build P0 | Proactivity engine + approval + browser tool | 4 days | Proactive messages firing |
| Build P1 | Monitor skills + profile learning | 3 days | Full monitor flow |
| Polish | Edge cases, opt-out, rate limiting | 2 days | Production release |

---

# Review Rubric — Self-Score

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | 5 | 10.0 |
| User Stories | 1.5x | 4 | 6.0 |
| Success Metrics | 1.5x | 4 | 6.0 |
| Scope Definition | 1.0x | 4 | 4.0 |
| Technical Feasibility | 1.0x | 4 | 4.0 |
| Risk Assessment | 1.0x | 4 | 4.0 |
| **Total** | **8.0x** | | **34.0/40** |

**Normalized: (34.0 / 40) x 30 = 25.5/30**

**Verdict: Ready to build** (25.5 > 25 threshold)

### Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific scenarios
- [x] Conversation examples use natural language
- [x] "Not building" list has 4 items
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include failure signals
- [x] Cost estimate within budget ($1.03/user/month)
- [x] Star rating stated and justified (6★ → 7★)
- [x] RICE score: 24.5
- [x] Proactivity section defines frequency limits (max 5/day)
- [x] Edge cases include cold-start scenario
