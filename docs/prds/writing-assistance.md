# Writing Assistance: AI-Powered Drafting, Translation, and Proofreading

**Author:** AI Assistant
**Date:** 2026-02-17
**Status:** In Development
**Star Rating:** 4★ → 6★ (from "no writing capability" to "drafts, translates, proofreads, and writes posts in user's voice")
**RICE Score:** 37.3 (Reach 70% x Impact 2.0 x Confidence 80% / Effort 3 wks)

---

## 1. Problem Statement

### What problem are we solving?

Users need to write messages, emails, quotes, reviews, and social posts every day — but composing text on a phone is slow and painful. 70% of target users send 5+ messages daily that require thought (not just "ok" or "thanks"). They switch between the bot and other apps to draft text, translate between languages, or fix grammar. Every app switch breaks the single-interface promise and adds friction.

### The Maria Test

> Maria needs to write an email to Emma's school about a schedule change. English is her second language and she worries about sounding professional. She currently types a draft in Notes, copies it to Google Translate to check phrasing, edits it, then pastes into Gmail. This takes 15 minutes for a 3-sentence email. She needs to say "write an email to school about Emma being late tomorrow" and get a polished draft in 10 seconds.

### The David Test

> David gets a 1-star Google review from an unhappy client. He needs to respond professionally but he's on a job site with dirty hands and limited time. He currently ignores reviews for days or types a defensive reply he later regrets. He texts "write a response to this bad review: customer says we left a mess" and needs a professional, empathetic response in seconds — ready to copy-paste.

### Who else has this problem?

70% of target users. Anyone who communicates in writing — parents emailing teachers, business owners responding to reviews, bilingual users translating between family language and English, freelancers sending quotes. Writing Assistance is RICE 37.3, Phase 1 MVP #4 priority. It's the bridge between "finance bot" and "life assistant."

---

## 2. Solution Overview

### What are we building?

Four skills that draft messages, translate text, write content for platforms, and proofread — all via natural conversation. Uses Claude Sonnet for creative drafting and writing (quality matters), Claude Haiku for fast proofreading (mechanical task). All skills respect the user's language preference and adapt tone to context.

### Conversation Example

**Maria's scenario:**
```
Maria: write an email to school saying Emma will be late tomorrow, dentist appointment at 9am
Bot: Here's a draft:

Subject: Emma Rodriguez — Late Arrival Tomorrow

Dear [Teacher's Name],

Emma will arrive late tomorrow due to a dentist appointment at 9:00 AM. She should be at school by 10:30. Please let me know if she'll miss anything important.

Thank you,
Maria Rodriguez

Want me to change anything?

Maria: make it shorter, less formal
Bot: Updated:

Hi,

Just a heads up — Emma has a dentist appointment at 9 AM tomorrow so she'll be in around 10:30.

Thanks,
Maria

Maria: translate that to Spanish
Bot: Hola,

Solo quería avisar — Emma tiene cita con el dentista a las 9 AM mañana, así que llegará alrededor de las 10:30.

Gracias,
Maria
```

**David's scenario:**
```
David: write a response to this bad review: customer says we left a mess after the bathroom job
Bot: Here's a professional response:

Thank you for your feedback. We take cleanliness seriously and I'm sorry we didn't meet your expectations on this job. I'd like to make it right — please call us at [your number] so we can send someone to clean up. We appreciate your business and want to ensure you're satisfied.

— David, D&D Plumbing

Want me to adjust the tone?

David: proofread this: "Were coming to fix the pipe tommorrow between 10-12, make sure someone is home"
Bot: Fixed 3 issues:

"We're coming to fix the pipe tomorrow between 10-12. Make sure someone is home."

• Were → We're (contraction)
• tommorrow → tomorrow (spelling)
• Added period between sentences
```

### What are we NOT building?

1. Revision loop orchestrator (LangGraph) — P1 feature, P0 uses single-turn generation with follow-up via conversation history
2. Template library (saved email templates, review templates) — future iteration
3. Direct sending (email, SMS, social media posting) — requires channel integrations (Phase 2)
4. Document generation (PDF invoices, contracts) — separate domain
5. Grammar checking of all incoming messages — only explicit "proofread this" requests
6. Tone/style learning from user's history — P1, uses Mem0 profile data

---

## 3. User Stories

### P0 — Must Have (launch blockers)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | say "write an email about X" and get a draft | I compose messages in seconds, not minutes |
| 2 | User | say "translate this to Spanish" and get a translation | I communicate across languages without leaving the chat |
| 3 | User | say "write a review response about X" and get platform-ready text | I respond to reviews/posts professionally and quickly |
| 4 | User | say "proofread this" and get corrections with explanations | I catch errors before sending important messages |

### P1 — Should Have (expected within 2 weeks of launch)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | say "make it more formal" and get a revised version | I iterate on drafts without re-explaining the whole context |
| 2 | User | have the bot match my writing style | drafts sound like me, not a robot |
| 3 | User | see source/target language labels | I know what languages are being translated |

### P2 — Nice to Have (future iteration)

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | User | save frequently-used templates | I reuse common message formats |
| 2 | User | translate entire conversations | I understand multilingual group chats |

### Won't Have (explicitly excluded)

| # | Feature | Reason |
|---|---------|--------|
| 1 | LangGraph revision orchestrator | Over-scoped for P0 — conversation history handles follow-ups |
| 2 | Direct email/SMS sending | Requires channel integrations — Phase 2 |
| 3 | Template storage and management | Feature creep — simple skill.execute() is enough for P0 |
| 4 | Automatic tone matching from history | Requires Mem0 profile analysis — P1 |
| 5 | Document/PDF generation | Separate domain with different technical requirements |

---

## 4. Success Metrics

| Category | Metric | Target | How to Measure |
|----------|--------|--------|----------------|
| **Activation** | % of users who use a writing skill in first 7 days | > 30% | Count writing intents per new user |
| **Usage** | Writing requests per active user per week | > 1.5 | Aggregate on intent logs |
| **Quality** | % of drafts used without revision request | > 60% | Track if next message is a revision request |
| **Retention** | % of writing users active in week 2 | > 45% | Cohort analysis |
| **Satisfaction** | User follows up with "thanks" or "perfect" | > 40% | Sentiment analysis on next message |

### Leading Indicators (check at 48 hours)

- [ ] Users who draft a message send "thanks" or copy the text (implicit acceptance)
- [ ] Translation requests come from bilingual users (not just curiosity)

### Failure Signals (trigger re-evaluation)

- [ ] > 50% of drafts receive immediate revision requests (tone/length miss)
- [ ] Users try once and never use writing skills again (one-and-done pattern)
- [ ] Proofread returns no changes on text with obvious errors (quality failure)

---

## 5. Technical Specification

### Architecture

| Component | Detail |
|-----------|--------|
| **Orchestrator** | None for P0 — single-turn skill.execute(). P1 adds LangGraph revision loop. |
| **Skills** | 4 new: `draft_message`, `translate_text`, `write_post`, `proofread` |
| **APIs** | Anthropic API (existing) — Claude Sonnet for drafting, Haiku for proofread |
| **Models** | Claude Sonnet 4.5 (draft_message, translate_text, write_post), Claude Haiku 4.5 (proofread) |
| **Database** | None new — uses existing conversation_messages for history |
| **Background Jobs** | None |

### Data Model

No new tables. Writing requests are logged in `conversation_messages` (existing) and `usage_logs` (existing). User's `preferred_language` from profile is used for translation defaults.

### Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Empty writing request ("write something") | Bot asks: "What would you like me to write? Give me the topic and who it's for." |
| Translation with no target language | Default to user's `preferred_language`. If same as source, ask "Which language should I translate this to?" |
| Very long text for proofreading (> 2000 chars) | Process in full — Claude handles long context. Truncate output if > 4096 chars for Telegram. |
| User asks to proofread already-correct text | Bot responds: "Looks good — no changes needed." |
| Ambiguous intent (draft vs. proofread) | Intent detection uses keywords: "write/draft/compose" → draft_message; "check/proofread/fix" → proofread |
| User writes in Russian, requests English draft | Follow explicit instruction — draft in English regardless of conversation language |
| First-time user with no profile | Works immediately — uses general professional tone. No onboarding needed. |
| Harmful content request | Guardrails (`check_input`) blocks before skill runs |

### Cost Estimate

| Component | Cost per interaction | Monthly @ 1K users |
|-----------|---------------------|---------------------|
| Claude Sonnet (draft/translate/write) | ~$0.005 | $500 (100K queries) |
| Claude Haiku (proofread) | ~$0.001 | $50 (50K queries) |
| **Total** | | **~$2.20/user** |

Within $3-8/month budget.

---

## 6. Proactivity Design

N/A for P0. Writing is reactive — users ask, bot writes.

### Rules

- No proactive writing messages in P0.
- P1 consideration: after user sends a long, error-filled message, offer "Want me to clean that up before you send it?" (max 1/day, only in coaching comm_mode).

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Tone mismatch — draft sounds wrong for context | Medium | Medium | System prompt includes detailed tone guidance (professional, casual, empathetic). User can request revision. P1 adds style learning. |
| Translation quality for non-European languages | Medium | Medium | Claude Sonnet handles 50+ languages well. Add disclaimer for rare languages. |
| Intent confusion: draft_message vs. general_chat | Medium | Medium | Priority rules: "write/draft/compose" keywords → writing domain. Pure conversation → general_chat. |
| Proofread misses errors or introduces new ones | Low | High | Use Claude Haiku which excels at mechanical tasks. Show changes explicitly (not silently). |
| Users expect direct sending (email, SMS) | Medium | Low | Bot says "Here's your draft — copy and send when ready." P2 adds channel integrations. |

### Dependencies

- [x] Anthropic API key (existing — used for multiple skills)
- [x] Phase 1 Core Generalization (domain router, writing domain defined in domains.py)
- [x] IntentData schema (writing_topic, target_language, target_platform already defined)

---

## 8. Timeline

| Phase | Scope | Duration | Milestone |
|-------|-------|----------|-----------|
| Design | PRD (this document) | 0.5 day | PRD approved |
| Build P0 | 4 skills + agent + intents + tests | 1 day | All tests pass |
| Build P1 | Revision loop (LangGraph), tone matching | 2 days | Iterative drafting works |
| Polish | Edge cases, language detection | 0.5 day | Production ready |

---

# Review Rubric

## Score Calculation

| Criterion | Weight | Score (1-5) | Weighted | Justification |
|-----------|--------|-------------|----------|---------------|
| Problem Clarity | 2.0x | 5 | 10.0 | Pain is vivid and daily: Maria's 15-min email, David's ignored reviews. 70% reach is well-supported — everyone writes. |
| User Stories | 1.5x | 4 | 6.0 | Clear P0/P1/P2. Won't Have has 5 items. Deducted 1: revision loop is P1 but power users will want it immediately. |
| Success Metrics | 1.5x | 4 | 6.0 | Metrics are measurable. 3 failure signals defined. Deducted 1: "used without revision" metric is a proxy, not direct satisfaction. |
| Scope Definition | 1.0x | 5 | 5.0 | Tight: 4 skills, no new tables, no new APIs. Clear exclusion of LangGraph/sending/templates. |
| Technical Feasibility | 1.0x | 5 | 5.0 | Uses existing Anthropic client. Sonnet for quality, Haiku for speed. Zero new dependencies. |
| Risk Assessment | 1.0x | 4 | 4.0 | Key risks covered with concrete mitigations. Deducted 1: no quality benchmark for translation accuracy. |
| **Total** | **8.0x** | | **36.0/40** |

**Normalized: (36.0 / 40) x 30 = 27.0/30**

| Score | Verdict | Action |
|-------|---------|--------|
| **27.0** | **Ready to build** | Proceed to implementation |

---

## Auto-Check Checklist

- [x] Both Maria and David appear in the Problem Statement with specific, believable scenarios
- [x] Conversation examples use natural language (not formal commands)
- [x] "Not building" list has at least 3 items (has 5)
- [x] Every P0 user story maps to a conversation example
- [x] Success metrics include at least one failure signal (3 defined)
- [x] Cost estimate is within $3-8/month per user ($2.20)
- [x] Star rating is stated and justified (4★ → 6★)
- [x] RICE score matches PRIORITIZATION.md (37.3)
- [x] Proactivity section defines frequency limits (N/A for P0, max 1/day for P1)
- [x] Edge cases include "no history" cold-start scenario (works immediately, general professional tone)
