# Research & Answers: AI-Powered Q&A and Web Search

**Author:** AI Assistant
**Date:** 2026-02-17
**Status:** In Development
**Star Rating:** 4★ → 6★ (from "no research capability" to "answers questions with web-grounded facts and structured comparisons")
**RICE Score:** 42.7 (Reach 80% x Impact 2.0 x Confidence 80% / Effort 3 wks)

---

## 1. Problem Statement

### What problem are we solving?

Users ask the bot factual questions ("what time does Costco close?", "how many cups in a gallon?") and get routed to `general_chat`, which uses Claude Haiku without web access. The bot invents answers or says "I can't help with that." 80% of target users ask at least one factual question per day. Every wrong answer erodes trust. Every "I can't do that" pushes the user back to Google — breaking the single-interface promise.

### The Maria Test

> Maria texts "what's a good recipe for chicken and broccoli?" and the bot gives a vague 2-sentence reply because Haiku has no web access and the general_chat prompt says "if question is off-topic, say you can help with finances." Maria opens Google, finds a recipe, and forgets about the bot for the rest of the day. She needed a useful answer in the same chat.

### The David Test

> David texts "what's the going rate for a bathroom remodel in Queens?" and the bot says something generic. David wanted a real answer with current market data. He Googles it, finds a HomeAdvisor article, and texts his buddy instead of the bot. The bot failed to be the "smart friend who knows things."

### Who else has this problem?

80% of target users. Research & Answers is the #3 RICE module (42.7) and the lowest-effort module in Phase 1 MVP (3 weeks). Users who can't get basic questions answered don't trust the bot with higher-stakes tasks.

---

## 2. Solution Overview

### What are we building?

Three skills that answer factual questions, search the web with grounded results, and compare options — all via natural language. Uses Gemini Flash for fast factual answers, Gemini with Google Search grounding for web research, and Claude Sonnet for structured comparisons.

### Conversation Example

**Maria's scenario:**
```
Maria: how many cups in a gallon?
Bot: 16 cups in a gallon (128 oz).

Maria: what's a quick chicken and broccoli recipe?
Bot: Quick chicken broccoli stir-fry (20 min):
• Cut 1 lb chicken into pieces, season with salt/pepper
• Stir-fry chicken 5 min, add 2 cups broccoli florets
• Mix 3 tbsp soy sauce + 1 tbsp honey + 1 tsp garlic
• Pour sauce over, cook 3 min. Serve over rice.

Maria: compare Costco vs Sam's Club for a family of 4
Bot: Costco vs Sam's Club:
• Membership: Costco $65/yr, Sam's Club $50/yr
• Food quality: Costco — better organic/Kirkland brand. Sam's — more name brands.
• Locations: Sam's has more NYC-area stores. Costco — 1 in Brooklyn (Sunset Park).
• Bottom line: Costco for quality, Sam's for convenience and price.
```

**David's scenario:**
```
David: what's the going rate for a bathroom remodel in Queens?
Bot: Bathroom remodel in Queens (2024-2025 rates):
• Basic update (fixtures, paint): $8K-$15K
• Mid-range (new tile, vanity, tub): $15K-$30K
• High-end (custom, heated floors): $30K-$50K+
Source: HomeAdvisor, Angi local data.

David: compare PEX vs copper pipe for residential
Bot: PEX vs copper pipe:
• Cost: PEX $0.40-$0.80/ft, copper $2-$4/ft
• Installation: PEX — faster, fewer fittings. Copper — soldering required.
• Durability: Copper 50+ years. PEX 25-50 years (newer, less field data).
• Best for David: PEX for cost savings on residential jobs. Copper for high-end clients who want longevity.
```

### What are we NOT building?

1. Real-time data feeds (stock prices, flight status) — requires monitoring infrastructure (Phase 3)
2. Multi-step autonomous research agents — over-scoped for MVP, requires LangGraph orchestrator
3. Source citation with clickable links — P1 feature, not P0
4. Image/document research (reverse image search, PDF analysis) — separate domain
5. Location-aware search (nearby restaurants) — requires user location, P1

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | ask a factual question and get an answer | I don't leave the chat for Google |
| 2 | User | search the web for current info | I get up-to-date answers, not stale LLM knowledge |
| 3 | User | compare two options side-by-side | I make decisions faster without tab-switching |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | see sources for web search results | I verify the information if needed |
| 2 | User | ask follow-up questions | the bot remembers what we were discussing |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | save a research result as a note | I reference it later without re-searching |
| 2 | User | get location-aware results | "best pizza near me" works without specifying location |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | Autonomous multi-step research | Requires LangGraph orchestrator — Phase 2+ |
| 2 | Real-time data monitoring | Requires monitoring infrastructure — Phase 3 |
| 3 | Academic/scholarly search | Niche audience, low RICE for consumer/SMB market |
| 4 | Image-based search | Different domain, separate skill |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who ask a question in first 48h | > 50% | Count research intents per new user |
| **Usage** | Research queries per active user per week | > 2 | Aggregate on intent logs |
| **Quality** | % of answers rated useful (implicit: no follow-up "that's wrong") | > 80% | Track correction patterns |
| **Retention** | % of research users active in week 2 | > 55% | Cohort analysis |

### Leading Indicators (check at 48 hours)

- [ ] Users ask 2+ questions without switching to Google
- [ ] Web search returns grounded answers (not hallucinated)

### Failure Signals (trigger re-evaluation)

- [ ] > 30% of research queries result in "I don't know" or visibly wrong answers
- [ ] Users ask one question and never use research again (one-and-done pattern)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None — skills are single-turn LLM calls |
| **Skills** | 3 new: `quick_answer`, `web_search`, `compare_options` |
| **APIs** | Gemini API (existing), Google Search via Gemini grounding (no new API key) |
| **Models** | Gemini 3 Flash (quick_answer, web_search), Claude Sonnet 4.6 (compare_options) |
| **Database** | None new — uses existing conversation_messages for history |
| **Background Jobs** | None |

### Data Model

No new tables. Research queries are logged in `conversation_messages` (existing) and `usage_logs` (existing, Phase 1 migration).

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| User asks a dangerous/harmful question | Guardrails (`check_input`) blocks before skill runs |
| Gemini search grounding unavailable | Fall back to LLM knowledge, add disclaimer: "based on my training data" |
| User asks about very recent events | Web search returns current results; quick_answer adds "as of my last update" caveat |
| Empty or nonsensical query | Bot asks: "What would you like to know?" |
| Comparison with 3+ items | Handle up to 4 items. 5+ items: "Pick your top 3-4 and I'll compare those." |
| User asks in Russian | Respond in Russian (language matching per context.language) |
| First-time user asks a question | Works immediately — no onboarding required for research |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Gemini Flash (quick_answer) | ~$0.001 | $200 (200K queries) |
| Gemini Flash + search grounding (web_search) | ~$0.003 | $300 (100K queries) |
| Claude Sonnet (compare_options) | ~$0.005 | $100 (20K queries) |
| **Total** | | **~$2.00/user** |

Within $3-8/month budget.

---

## 6. Proactivity Design

N/A for P0. Research is reactive by nature — users ask, bot answers.

### Rules

- No proactive research messages in P0.
- P1 consideration: "Did you know?" facts related to user's recent queries (max 1/week).

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Gemini search grounding returns low-quality results | Medium | Medium | Fall back to LLM knowledge with disclaimer. P1: add source filtering. |
| Intent confusion: "quick_answer" vs "general_chat" | Medium | Medium | Priority rules: any question mark or "what/how/why/when" → research domain. Chitchat stays in general_chat. |
| LLM hallucination on factual questions | Medium | High | Web search grounding for anything that needs current data. Quick_answer for timeless facts only. |
| Compare_options produces biased comparisons | Low | Medium | System prompt requires balanced, factual comparison. No recommendations unless user asks. |

### Dependencies

- [x] Google AI API key (existing — used for intent detection and OCR)
- [x] Gemini search grounding (included in Gemini API, no additional cost)
- [x] Phase 1 Core Generalization (domain router, research domain defined)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD (this document) | 0.5 day | PRD approved |
| Build P0 | 3 skills + agent + intents + tests | 1 day | All tests pass |
| Build P1 | Source citations, follow-up context | 0.5 day | Enhanced responses |
| Polish | Edge cases, language matching | 0.5 day | Production ready |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted | Justification |
|-----------|--------|-------------|----------|---------------|
| Problem Clarity | 2.0x | 5 | 10.0 | Pain is universal (80% reach) and specific: users leave the chat for Google. Maria and David scenarios are daily occurrences. |
| User Stories | 1.5x | 4 | 6.0 | Clear P0/P1/P2. Won't Have has 4 items. Deducted 1: follow-up context is P1 but users expect it from P0. |
| Success Metrics | 1.5x | 4 | 6.0 | Metrics are measurable. Failure signals defined. Deducted 1: "useful answer" metric relies on implicit signal (no correction), not explicit feedback. |
| Scope Definition | 1.0x | 5 | 5.0 | Tight: 3 skills, no new tables, no new dependencies. Clear "not building" list. |
| Technical Feasibility | 1.0x | 5 | 5.0 | Uses existing Gemini client. Search grounding is built into Gemini API. Claude Sonnet for comparisons. Zero new dependencies. |
| Risk Assessment | 1.0x | 4 | 4.0 | Key risks covered. Hallucination mitigation is concrete (web grounding). Deducted 1: no A/B test plan for quality measurement. |
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
- [x] Cost estimate is within $3-8/month per user ($2.00)
- [x] Star rating is stated and justified (4★ → 6★)
- [x] RICE score matches PRIORITIZATION.md (42.7)
- [x] Proactivity section defines frequency limits (N/A for P0, max 1/week for P1)
- [x] Edge cases include "no history" cold-start scenario (works immediately, no onboarding needed)
