# PRD Template — AI Life Assistant

Use this template for every feature or module. Fill in every section. If a section doesn't apply, write "N/A" with a one-line explanation. Do not delete sections.

After completing the PRD, score it using the **Review Rubric** at the bottom.

---

# [Module Name]: [Feature Title]

**Author:** [Name]
**Date:** [YYYY-MM-DD]
**Status:** Draft | In Review | Approved | In Development
**Star Rating:** [Target ★ rating from 11_STAR_EXPERIENCE.md, with justification]
**RICE Score:** [From PRIORITIZATION.md]

---

## 1. Problem Statement

### What problem are we solving?

[One paragraph. Be specific about the pain, not the solution. Include frequency and severity.]

### The Maria Test

> Maria is [specific scenario where she hits this problem]. She currently [workaround she uses]. This costs her [time/effort/frustration].

### The David Test

> David is [specific scenario where he hits this problem]. He currently [workaround he uses]. This costs him [time/money/missed opportunities].

### Who else has this problem?

[Describe the broader user segment. How many of our target users face this? How do we know?]

---

## 2. Solution Overview

### What are we building?

[2-3 sentences describing the solution at a high level. Focus on what changes for the user, not the implementation.]

### Conversation Example

Show a realistic conversation flow. Use natural language, not formal scripts.

**Maria's scenario:**
```
Maria: remind me to pick up emma at 3:15
Bot: Got it — I'll ping you at 3:15 for Emma pickup. 📍

[At 3:15 PM]
Bot: Time to pick up Emma! Traffic from your location is light — about 12 minutes.

Maria: thanks, also add milk to the grocery list
Bot: Added milk. Your list has 6 items now — want to see it?
```

**David's scenario:**
```
David: schedule mike for the elm st job tomorrow morning
Bot: Mike's booked for 10am at Elm St tomorrow (his usual morning slot). I'll let him know.

David: actually make it 11
Bot: Moved to 11am. Mike still has the 2pm on Oak Ave — no conflict. Updated and notified.
```

### What are we NOT building?

[Explicitly list things that are out of scope. This prevents scope creep during development.]

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | [action] | [outcome] |
| 2 | User | [action] | [outcome] |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | [action] | [outcome] |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | [action] | [outcome] |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | [feature] | [why we're not building it] |

---

## 4. Success Metrics

Define how we know this feature is working. Every metric needs a target and a measurement method.

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of new users who complete [core action] within 24h | > 60% | Supabase event tracking |
| **Usage** | [Core action] per active user per week | > X | Aggregate query |
| **Retention** | % of users who use feature in week 2 | > 40% | Cohort analysis |
| **Satisfaction** | User-reported satisfaction (1-5 scale via bot) | > 4.0 | In-chat survey after day 7 |
| **Business** | Impact on overall churn rate | -X% | Subscription analytics |

### Leading Indicators (check at 48 hours)

- [ ] [Early signal 1]
- [ ] [Early signal 2]

### Failure Signals (trigger re-evaluation)

- [ ] [What would indicate the feature isn't working]
- [ ] [At what threshold do we reconsider the approach]

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | [Which LangGraph orchestrator handles this] |
| **Skills** | [List of skills involved, new and existing] |
| **APIs** | [External APIs needed] |
| **Models** | [Which LLM models and why — reference TASK_MODEL_MAP] |
| **Database** | [New tables, columns, or indexes needed] |
| **Background Jobs** | [Any Taskiq tasks needed] |

### Data Model

```sql
-- New tables or columns needed
CREATE TABLE IF NOT EXISTS [table_name] (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    -- [columns]
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| [Edge case 1] | [How the bot handles it] |
| [Edge case 2] | [How the bot handles it] |
| User sends ambiguous input | [Clarification strategy] |
| External API is down | [Fallback behavior] |
| User has no history yet | [Cold-start behavior] |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| LLM calls | $X | $X |
| API calls | $X | $X |
| Storage | $X | $X |
| **Total** | **$X** | **$X** |

Must stay within $3-8/month per user budget.

---

## 6. Proactivity Design

How does this feature work when the user hasn't asked for anything?

| Trigger | Action | Frequency | Channel |
|---------|--------|-----------|---------|
| [Condition that triggers proactive behavior] | [What the bot does] | [How often max] | [Morning brief / standalone / etc.] |

### Rules

- Proactive messages must be useful, not annoying. Max [N] proactive messages per day across all features.
- User can say "stop reminding me about X" and the bot respects it permanently.
- Every proactive message must be actionable — the user can respond and something happens.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk 1] | High/Med/Low | High/Med/Low | [How we reduce it] |
| [Risk 2] | High/Med/Low | High/Med/Low | [How we reduce it] |

### Dependencies

- [ ] [External dependency 1 — status]
- [ ] [External dependency 2 — status]

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD + conversation flows | X days | PRD approved |
| Build P0 | Core functionality | X days | Internal demo |
| Build P1 | Expected features | X days | Beta release |
| Polish | Edge cases, proactivity | X days | Production release |

---

# Review Rubric

Score every PRD before development begins. Be honest — a tough review now prevents wasted engineering later.

## Scoring Guide

### 1. Problem Clarity (Weight: 2x)

| Score | Description |
|-------|-------------|
| 5 | Problem is specific, validated with real user signals, and quantified. Maria and David tests are vivid and reveal genuine pain. |
| 4 | Problem is clear and well-articulated. Personas are realistic. Minor gaps in validation data. |
| 3 | Problem is stated but generic. Persona scenarios feel constructed rather than observed. |
| 2 | Problem is vague or assumed. Personas are superficial. No evidence of user need. |
| 1 | Problem is missing or is actually a solution masquerading as a problem. |

### 2. User Stories (Weight: 1.5x)

| Score | Description |
|-------|-------------|
| 5 | P0/P1/P2 are clearly differentiated. Stories are specific and testable. Won't Have list shows disciplined scoping. |
| 4 | Good story coverage. Prioritization is reasonable. Minor gaps. |
| 3 | Stories exist but are too broad. Prioritization is unclear or everything is P0. |
| 2 | Stories are vague or incomplete. No clear prioritization. |
| 1 | Missing or just a bullet list of features. |

### 3. Success Metrics (Weight: 1.5x)

| Score | Description |
|-------|-------------|
| 5 | Metrics are specific, measurable, time-bound, and tied to business outcomes. Leading indicators and failure signals are defined. |
| 4 | Good metrics with reasonable targets. Minor gaps in measurement plan. |
| 3 | Metrics exist but targets are arbitrary or unmeasurable. |
| 2 | Only vanity metrics (e.g., "total messages sent"). No failure signals. |
| 1 | No metrics, or metrics that can't distinguish success from failure. |

### 4. Scope Definition (Weight: 1x)

| Score | Description |
|-------|-------------|
| 5 | Scope is tight and focused. Clear "not building" list. Conversation examples show exactly what ships. Timeline is realistic. |
| 4 | Scope is mostly clear. Minor ambiguity in boundaries. |
| 3 | Scope is broad. "Not building" list is thin. Could be 2 separate PRDs. |
| 2 | Scope is unclear or unrealistically large. No exclusion list. |
| 1 | Scope is unbounded or contradictory. |

### 5. Technical Feasibility (Weight: 1x)

| Score | Description |
|-------|-------------|
| 5 | Architecture fits existing stack. Cost is within budget. Edge cases are thorough. Data model is sound. |
| 4 | Technically sound with minor unknowns. Cost is manageable. |
| 3 | Some technical risks unaddressed. Cost estimate is rough. |
| 2 | Significant technical unknowns. May require new infrastructure. |
| 1 | Technically infeasible or requires fundamental architecture changes. |

### 6. Risk Assessment (Weight: 1x)

| Score | Description |
|-------|-------------|
| 5 | Risks are specific and realistic. Mitigations are actionable. Dependencies are tracked. Failure modes are identified. |
| 4 | Key risks identified with reasonable mitigations. |
| 3 | Risks are generic ("it might not work"). Mitigations are vague. |
| 2 | Only obvious risks listed. No real mitigations. |
| 1 | No risk assessment, or "no risks identified." |

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted |
|-----------|--------|-------------|----------|
| Problem Clarity | 2.0x | __ | __ |
| User Stories | 1.5x | __ | __ |
| Success Metrics | 1.5x | __ | __ |
| Scope Definition | 1.0x | __ | __ |
| Technical Feasibility | 1.0x | __ | __ |
| Risk Assessment | 1.0x | __ | __ |
| **Total** | **8.0x** | | **__/40** |

Normalize to 30-point scale: **(Total / 40) × 30 = __/30**

| Score | Verdict | Action |
|-------|---------|--------|
| **25-30** | Ready to build | Proceed to implementation |
| **20-24** | Almost there | Address specific gaps, re-score |
| **15-19** | Needs rework | Major revision required — revisit problem and scope |
| **< 15** | Start over | Fundamental rethinking — problem may not be worth solving |

## Auto-Check Checklist

Before submitting, verify:

- [ ] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [ ] Conversation examples use natural language (not formal commands)
- [ ] "Not building" list has at least 3 items
- [ ] Every P0 user story maps to a conversation example
- [ ] Success metrics include at least one failure signal
- [ ] Cost estimate is within $3-8/month per user
- [ ] Star rating is stated and justified
- [ ] RICE score matches PRIORITIZATION.md
- [ ] Proactivity section defines frequency limits
- [ ] Edge cases include "no history" cold-start scenario
