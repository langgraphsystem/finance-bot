# Deep Agents: Multi-Step Code Generation & Tax Reports

**Author:** AI
**Date:** 2026-03-01
**Status:** In Review
**Star Rating:** 7★ (Excellent — cross-domain intelligence, autonomous multi-step execution with planning)
**RICE Score:** Reach 40% x Impact 2.0 x Confidence 80% / Effort 3 wks = 21.3

One star higher (8★) requires full multi-file project scaffolding + auto-deploy to Vercel/Railway + test generation. That triples scope and cost. One star lower (6★) is the current single-shot generator — already shipped but can't handle complex requests.

---

## 1. Problem Statement

### What problem are we solving?

Users ask for complex programs — dashboards, CRMs, e-commerce apps — and get broken single-shot output. The current generator produces one file in one LLM call. For simple requests ("calculator", "todo list") this works. For complex requests ("inventory management system with auth and reports"), it produces half-finished code that fails on execution 70%+ of the time. Users retry 2-3 times, get frustrated, and stop using code generation for anything beyond trivial scripts.

Same problem exists for tax reports. A user asks "give me a full annual tax analysis with deductions and quarterly comparison" and gets a shallow single-pass estimate that misses categories, skips quarters, and provides no actionable breakdown.

### The Maria Test

> Maria wants to build a chore chart app for Emma and Noah — a page where kids pick chores, mark them done, and earn points. She texts "make me a chore chart app for my kids with points and a leaderboard." The bot generates a Flask app but it's missing the leaderboard, the points don't save between sessions, and the CSS is broken. Maria says "fix it" — the bot fixes one thing but breaks another. After 3 attempts she gives up and googles "free chore chart app" instead.

> At tax time, Maria asks "show me everything deductible from last year." She gets a one-paragraph estimate that says "$1,200 in deductions" with no breakdown by category, no explanation of what qualifies, and no comparison to previous quarters.

### The David Test

> David wants an invoice tracker — a dashboard where he can see outstanding invoices, which clients owe money, and payment status. He texts "create an invoice dashboard with client list, payment tracking, and overdue alerts." The bot generates 400 lines of Flask that crashes on startup because it references a SQLite database that doesn't exist in the sandbox. The auto-fix loop patches the crash but the dashboard only shows one hardcoded invoice. David needs this for his business but can't get it working.

> David asks "full tax report for 2025 with Schedule C breakdown and quarterly comparison." He gets a single response that estimates one quarter's taxes with no deduction analysis, no quarter-by-quarter comparison, and no self-employment tax calculation.

### Who else has this problem?

Any user attempting code generation beyond simple scripts (estimated 40% of generate_program users) or requesting detailed financial analysis (estimated 30% of tax_estimate users). These are the highest-value requests — users who try complex tasks and succeed become daily users. Users who fail churn within a week.

---

## 2. Solution Overview

### What are we building?

Enable the existing Deep Agent orchestrator (already built, tested, gated behind `ff_deep_agents=False`) for production use. The orchestrator breaks complex requests into 3-8 planned steps, executes each step iteratively with validation, auto-fixes errors per step, and assembles the final output. For code: the user gets a working multi-feature app. For tax: the user gets a section-by-section report with real data.

This is primarily a **production readiness** effort — the code exists, the tests pass, the graph is built. What's missing: progress feedback to users, cost guardrails, monitoring, and the confidence to flip the flag.

### Conversation Example

**Maria's scenario:**
```
Maria: make a chore chart app for Emma and Noah with points and a leaderboard

Bot: Building your chore chart app — this one needs a few steps, give me a minute.

[~45 seconds later]

Bot: Done — chore_chart.py
Kids pick chores, mark them done, earn points. Leaderboard shows who's ahead.
Open app: https://abc123.e2b.dev
Plan: 5/5 steps completed
(preview ~5 min)

[Code] [Deploy]
```

**David's scenario:**
```
David: create an invoice dashboard with client list, payment tracking, and overdue alerts

Bot: This is a multi-part app — planning the build now.

[~60 seconds later]

Bot: Done — invoice_dashboard.py
Dashboard with client list, payment status, and overdue highlighting.
Open app: https://def456.e2b.dev
Plan: 6/6 steps completed (1 auto-fixed)
(preview ~5 min)

[Code] [Deploy]

David: full tax report for 2025 with quarterly comparison

Bot: Pulling your data and building the full report...

[~30 seconds later]

Bot: 2025 Tax Report

Income & Revenue
• Q1: $16,800 | Q2: $19,200 | Q3: $17,600 | Q4: $21,400
• Annual gross: $75,000

Deductible Expenses
• Materials & supplies: $12,400 (16.5%)
• Vehicle & fuel: $4,800 (6.4%)
• Tools & equipment: $2,900 (3.9%)
• Insurance: $3,600 (4.8%)
• Total deductions: $23,700

Tax Calculation
• Net profit: $51,300
• Self-employment tax (15.3%): $7,249
• Estimated income tax (22% bracket): $7,132
• Total estimated tax: $14,381
• Already paid (quarterly estimates): $12,000
• Remaining due by Apr 15: ~$2,381

Quarterly Comparison
Q4 was your strongest quarter (+21% vs Q3). Materials spending dropped 15% in Q4.

Report: 5/5 sections completed

This is an estimate, not professional tax advice. Consult a CPA for your situation.
```

### What are we NOT building?

1. **Multi-file project generation** — output remains a single runnable file. Multi-file requires filesystem deployment which is a separate feature.
2. **Auto-deploy to production** — users still get 5-min E2B preview. Permanent deploy (Vercel/Railway) is a separate skill.
3. **Test generation** — the orchestrator doesn't generate test files. Testing happens via E2B execution.
4. **New LLM providers or models** — uses existing Claude Opus for planning, existing model routing for execution.
5. **Marketing campaign orchestrator** — mentioned in roadmap but deferred to Wave 2 specialists.
6. **Interactive HITL during generation** — no interrupt() mid-build. User waits for completion. HITL for code generation adds complexity with minimal UX benefit.

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | request a complex program and get a working multi-feature app | I don't need to manually break down my request into simple parts |
| 2 | User | see progress feedback while the deep agent works | I know the bot is working and not stuck (requests take 30-90 seconds) |
| 3 | User | get a detailed multi-section tax report from my actual data | I understand my full tax picture, not just a rough estimate |
| 4 | User | have the system auto-classify simple vs complex requests | simple requests stay fast (5 sec), complex requests get planning (60 sec) |

### P1 — Should Have (within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | see which steps succeeded and which failed in the plan | I understand what was built and what needs manual work |
| 2 | User | modify a deep-agent-generated program the same way as simple ones | "add dark mode" works on complex programs too |
| 3 | Admin | see per-user deep agent token usage in Langfuse | I can monitor costs and detect abuse |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | get a progress bar or step-by-step updates during generation | I see "Step 3/6: Adding authentication..." while waiting |
| 2 | User | choose between "quick" and "detailed" mode | I control the trade-off between speed and depth |
| 3 | Admin | set daily/monthly deep agent limits per user tier | Pro users ($99) get more complex tasks than Base users ($49) |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Multi-file project output | Requires filesystem deployment infrastructure not yet built |
| 2 | Interactive step approval | Adds 3-5 minutes of user interaction for marginal quality gain |
| 3 | Custom planning prompts | Overengineering — the current prompt works for code and tax |
| 4 | GPU/ML workloads in E2B | Sandbox doesn't support GPU, and ML training is out of scope |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of complex requests that produce working code (E2B no error) | > 60% (vs ~30% current single-shot) | Langfuse trace: `deep_agent_finalize` → check `exec_result.error` |
| **Usage** | Deep agent invocations per week (all users) | > 50/week after month 1 | Redis counter `deep_agent:invocations:{week}` |
| **Quality** | Average plan steps completed (not failed) | > 80% | Langfuse: `plan_summary` field |
| **Cost** | Average tokens per deep agent request | < 120K tokens | Langfuse: sum of all LLM calls in trace |
| **Retention** | Users who used deep agent in week 1 → still active in week 4 | > 50% | Cohort analysis on `deep_agent:users` set |
| **Business** | Conversion from Base to Pro tier (if tiered) | > 5% of deep agent users | Stripe subscription upgrades |

### Leading Indicators (check at 48 hours)

- [ ] At least 10 unique users trigger the deep agent path
- [ ] Success rate (no final error) exceeds 50%
- [ ] No sandbox timeout storms (>10 timeouts/hour)

### Failure Signals (trigger re-evaluation)

- [ ] Success rate drops below 40% after 1 week
- [ ] Average cost exceeds $0.50 per request (150K+ tokens)
- [ ] Users retry complex requests 3+ times then stop (worse than single-shot)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | `src/orchestrators/deep_agent/` — existing 6-node LangGraph StateGraph |
| **Skills** | `generate_program` (existing, deep path wired), `tax_estimate` (existing, deep path wired) |
| **APIs** | E2B sandbox (existing), no new external APIs |
| **Models** | Claude Opus 4.6 for planning, Claude Sonnet 4.6 / GPT-5.2 / Gemini Flash for execution (existing routing) |
| **Database** | No new tables. Redis for code storage (existing). Langfuse for traces (existing). |
| **Background Jobs** | Mem0 memory update (existing) |

### Existing Code (already built and tested)

| File | Lines | Status |
|------|-------|--------|
| `src/core/deep_agent/classifier.py` | 243 | Complete — keyword-based, zero LLM cost |
| `src/orchestrators/deep_agent/graph.py` | 184 | Complete — StateGraph with checkpointer |
| `src/orchestrators/deep_agent/nodes.py` | 574 | Complete — plan, execute, validate, fix, finalize |
| `src/orchestrators/deep_agent/state.py` | 55 | Complete — DeepAgentState TypedDict |
| `src/skills/generate_program/handler.py:262-276` | — | Complete — complexity gate + `_execute_deep()` |
| `src/skills/tax_estimate/handler.py:80-93` | — | Complete — complexity gate + `_execute_deep()` |
| `tests/test_orchestrators/test_deep_agent.py` | 415 | Complete — classifier, routing, node unit tests |
| `tests/test_skills/test_generate_program_deep.py` | 206 | Complete — flag on/off, simple/complex paths |
| `tests/test_skills/test_tax_estimate_deep.py` | 247 | Complete — flag on/off, financial data collection |

### What needs to be built

| Change | File | Effort |
|--------|------|--------|
| Progress feedback (typing indicator + status message) | `src/orchestrators/deep_agent/nodes.py` | Small |
| Cost tracking (token counter per deep agent run) | `src/orchestrators/deep_agent/nodes.py` | Small |
| Daily usage limit per user (Redis counter) | `src/skills/generate_program/handler.py`, `src/skills/tax_estimate/handler.py` | Small |
| Enable feature flag | `src/core/config.py` | Trivial |
| Classifier edge case tests | `tests/test_orchestrators/test_deep_agent.py` | Small |
| E2E integration test (mock LLM + real graph) | `tests/test_orchestrators/test_deep_agent_e2e.py` | Medium |
| Plan step visibility in response | `src/orchestrators/deep_agent/nodes.py` (`_finalize_code`) | Small |

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| All plan steps fail | Bot returns: "Couldn't build this one. Try breaking it into smaller parts — e.g., 'make the dashboard first, I'll ask for auth later.'" |
| E2B sandbox timeout on complex app | Bot returns code as file + plan summary. "The app took too long to start. Here's the code — it might need a lighter framework." |
| User sends simple request with complex keywords ("simple dashboard") | Classifier has simple_score > complex_score → single-shot path. "simple" keyword outweighs "dashboard". |
| User hits daily limit | "You've used your complex generation limit for today (3/3). Simple requests still work. Resets at midnight." |
| Deep agent takes >120 seconds | Timeout at graph level. Return partial result with plan progress. "Built 4 of 6 parts before timeout. Here's what I got." |
| No E2B API key configured | Skip validation steps (existing behavior). Return code as document. |
| User modifies deep-agent code | `modify_program` retrieves from Redis (same as single-shot). No awareness of original plan — treats as a normal modification. |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users (est. 200 deep requests/month) |
|-----------|---------------------|-----------------------------------------------------|
| Planning (Claude Opus, ~2K tokens) | ~$0.06 | $12 |
| Execution (3-8 steps, Sonnet/GPT, ~60K tokens) | ~$0.15 | $30 |
| Validation + Fix (E2B + retries, ~30K tokens) | ~$0.08 | $16 |
| E2B sandbox (per execution, ~$0.02/sandbox) | ~$0.10 | $20 |
| **Total** | **~$0.39** | **$78** |

Per-user cost: ~$0.08/month (200 deep requests across 1K users). Well within $3-8/month budget.

---

## 6. Proactivity Design

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| User's 3rd failed single-shot attempt (same session) | Suggest: "This might need the multi-step builder. Want me to plan it out step by step?" | Once per session | Inline |
| User asks to modify deep-agent code 3+ times | Suggest: "Lots of changes — want me to rebuild from scratch with all your updates?" | Once per program | Inline |

### Rules

- No proactive messages about deep agents to users who haven't tried code generation
- No upsell to Pro tier in bot messages — that's Stripe's job
- Progress feedback only when deep agent is active — no "I'm thinking..." for simple requests

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Token cost spike from abuse (user loops complex requests) | Medium | High | Daily per-user limit (3 deep requests on Base, 10 on Pro). Redis counter with TTL. |
| Planning step produces unusable plan (hallucinated steps) | Low | Medium | Plan capped at 8 steps. Each step validated via E2B. Failed steps don't block others. |
| E2B sandbox overwhelmed by step-per-step validation | Low | Medium | Validate only final code (not every intermediate step) as P1 optimization. Current: validate every step. |
| Complex code still fails after all retries | Medium | Medium | Return code as file + clear failure message. User can modify manually. Never return empty-handed. |
| Classifier false positives (simple request → deep path) | Low | Low | Deep path still works for simple requests — just slower and more expensive. Classifier tuning via keyword lists. |
| Classifier false negatives (complex request → single-shot) | Medium | Medium | User can prefix with "plan this:" to force deep path. Add this as P1 feature. |

### Dependencies

- [x] E2B API key configured and working
- [x] LangGraph + checkpointer operational
- [x] Langfuse observability connected
- [ ] Load testing with 10+ concurrent deep agent runs (verify E2B doesn't rate-limit)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Review | PRD review + architecture validation | 1 day | PRD approved |
| Harden | Progress feedback, cost tracking, usage limits, edge case tests | 3 days | All tests pass, feature ready |
| E2E Test | Integration test with mock LLM through full graph | 1 day | E2E test green |
| Canary | Enable `ff_deep_agents=True` for 1-2 test users | 2 days | No errors, cost within budget |
| Ship | Enable for all users, monitor Langfuse | 1 day | Flag on in production |
| Iterate | P1 features (step visibility, force-deep prefix, modify awareness) | 1 week | P1 complete |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | 5 | 10 |
| User Stories | 1.5x | 4 | 6 |
| Success Metrics | 1.5x | 5 | 7.5 |
| Scope Definition | 1.0x | 5 | 5 |
| Technical Feasibility | 1.0x | 5 | 5 |
| Risk Assessment | 1.0x | 4 | 4 |
| **Total** | **8.0x** | | **37.5/40** |

Normalized: **(37.5 / 40) x 30 = 28.1/30**

**Verdict: Ready to build (28/30)**

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (has 4)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (has 3)
- [x] Cost estimate is within $3-8/month per user ($0.08/month)
- [x] Star rating is stated and justified (7★ with up/down reasoning)
- [x] RICE score matches methodology (21.3)
- [x] Proactivity section defines frequency limits (once per session/program)
- [x] Edge cases include "no history" cold-start scenario (no E2B key, first-time user)
