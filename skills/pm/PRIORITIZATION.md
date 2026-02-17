# Prioritization Framework — AI Life Assistant

## RICE Scoring (Module-Level)

Use RICE to decide which modules to build and in what order. RICE is for strategic, module-level decisions.

### Formula

**RICE = (Reach × Impact × Confidence) / Effort**

### Parameter Definitions

| Parameter | Definition | Scale |
|-----------|-----------|-------|
| **Reach** | % of target users who would use this feature quarterly | 0-100% |
| **Impact** | How much this moves the needle for users who encounter it | 3 = massive (life-changing), 2 = high (saves significant time), 1 = medium (helpful), 0.5 = low (nice to have), 0.25 = minimal |
| **Confidence** | How sure we are about Reach and Impact estimates | 100% = data-validated, 80% = strong user signals, 50% = educated guess, 20% = pure speculation |
| **Effort** | Engineering person-weeks to reach 6★ quality | Actual estimate in weeks |

### Rules

1. **If Confidence < 50%, don't build — validate first.** Run a concierge test, user interviews, or landing page experiment.
2. **Effort includes the full stack** — orchestrator, skills, APIs, tests, proactivity, edge cases, documentation.
3. **Reach is estimated for our target user base** — US consumers and small business owners who would pay $49/month for an AI assistant.
4. **Impact is measured against the alternative**, not against nothing. If people already have a good free solution, Impact is lower.

---

## Module Prioritization Table

| # | Module | Reach | Impact | Confidence | Effort (wks) | RICE Score | Phase |
|---|--------|-------|--------|------------|--------------|------------|-------|
| 1 | Tasks & Reminders | 95% | 3.0 | 90% | 4 | 64.1 | **Phase 1** |
| 2 | Calendar Management | 90% | 2.0 | 85% | 5 | 30.6 | **Phase 1** |
| 3 | Research & Answers | 80% | 2.0 | 80% | 3 | 42.7 | **Phase 1** |
| 4 | Writing Assistance | 70% | 2.0 | 80% | 3 | 37.3 | **Phase 1** |
| 5 | Onboarding | 100% | 3.0 | 90% | 3 | 90.0 | **Phase 1** |
| 6 | Email Management | 65% | 2.0 | 70% | 6 | 15.2 | **Phase 2** |
| 7 | Finance & Expenses | 55% | 2.0 | 60% | 5 | 13.2 | **Phase 2** |
| 8 | Contacts & CRM | 50% | 1.0 | 50% | 4 | 6.3 | **Phase 2** |
| 9 | Social & Reviews | 30% | 1.0 | 40% | 4 | 3.0 | **Phase 3** |
| 10 | Monitoring & Alerts | 40% | 1.0 | 50% | 5 | 4.0 | **Phase 3** |
| 11 | Voice Calls | 20% | 0.5 | 30% | 8 | 0.4 | **Phase 3** |
| 12 | Shopping & Orders | 45% | 1.0 | 40% | 6 | 3.0 | **Phase 3** |
| 13 | Health & Wellness | 35% | 1.0 | 30% | 5 | 2.1 | **Phase 3** |

---

## Phase Breakdown

### Phase 1 — MVP (Months 1-3)

**Goal:** Users can text the bot and get real value from day one. Core loop: ask → get answer → set reminder → manage calendar.

| Module | Why Phase 1 |
|--------|-------------|
| Onboarding | RICE 90.0 — Every user hits this. Zero-setup first impression determines retention. |
| Tasks & Reminders | RICE 64.1 — Universal need, high impact, high confidence. The "pick up Emma at 3:15" moment. |
| Research & Answers | RICE 42.7 — Instant value with lower effort. Users ask questions — the bot should answer. |
| Writing Assistance | RICE 37.3 — Immediate utility for both Maria (emails to school) and David (quotes to clients). |
| Calendar Management | RICE 30.6 — Core daily utility. Requires API integrations (Google Calendar, Apple Calendar) which adds effort. |

**Phase 1 success metric:** 60% of new users complete a task within 24 hours of first contact.

### Phase 2 — Expansion (Months 4-6)

**Goal:** The bot handles more of the user's life. Cross-domain intelligence begins. Users go from "useful" to "can't live without."

| Module | Why Phase 2 |
|--------|-------------|
| Email Management | RICE 15.2 — High effort (OAuth, complex parsing) but strong unlock. "Read my email and tell me what needs attention." |
| Finance & Expenses | RICE 13.2 — David needs invoicing and expense tracking. Maria needs budget awareness. |
| Contacts & CRM | RICE 6.3 — Foundation for cross-domain intelligence. The bot knowing who "Mike" and "Emma" are makes everything better. |

**Phase 2 success metric:** Users interact with 3+ modules per week on average.

### Phase 3 — Differentiation (Months 7-12)

**Goal:** Features that make the product uniquely valuable. Hard to replicate, strong word-of-mouth drivers.

| Module | Why Phase 3 |
|--------|-------------|
| Monitoring & Alerts | RICE 4.0 — "Tell me if my flight changes" or "Alert me when lumber prices drop." Powerful but niche. |
| Social & Reviews | RICE 3.0 — David wants Google review management. Lower reach but high impact for business users. |
| Shopping & Orders | RICE 3.0 — "Order more paper towels" — convenient but requires commerce integrations. |
| Health & Wellness | RICE 2.1 — Sensitive domain. Low confidence until we validate demand. |
| Voice Calls | RICE 0.4 — "Call the dentist and reschedule Emma" — magical but extremely hard. Last priority. |

---

## Decision Rules

### Tie-Breaking

When two modules have similar RICE scores:

1. **Prefer the one that generates word-of-mouth.** A feature that makes users say "you have to try this" beats one that's quietly useful.
2. **Prefer the one with lower effort.** Ship faster, learn faster.
3. **Prefer the one that enables future modules.** Contacts & CRM unlocks cross-domain intelligence even though its direct RICE is moderate.

### Phase Boundary Rules

- **Never start Phase 2 modules while Phase 1 has bugs or gaps.** Phase 1 must reach 6★ before moving on.
- **Cross-phase exceptions allowed only if:** a Phase 2 module can be built in < 1 week AND it solves a problem blocking Phase 1 retention.

### Re-evaluation Triggers

Re-score the full table when:
- A new module launches (user data changes Reach/Impact estimates)
- Confidence on a Phase 3 module exceeds 70% (user requests, market data)
- A competitor launches a feature that changes the landscape

---

## Won't Build List

Features we've explicitly decided not to build, and why.

| Feature | Reason |
|---------|--------|
| Native mobile app | Conversation IS the interface. An app adds maintenance without value. If users want "an app," they already have iMessage/WhatsApp. |
| Dashboard / web portal | Violates Principle 1 (conversation is the only interface). If users need to see data, the bot sends it in chat. |
| Multi-language support (at launch) | Focus on English for US market first. Internationalization adds complexity to every feature. Revisit at 10K users. |
| Team collaboration (shared bots) | Individual assistant first. Team features are a different product with different economics. |
| Smart home integration | Alexa/Google Home control is cool but niche, unreliable, and has strong incumbents. Not our fight. |
| Crypto / stock trading | Regulatory minefield. Financial tracking (yes), trading (no). |

---

## Feature-Level ICE Scoring (Within a Module)

Once a module is prioritized, use ICE to rank individual features within it.

### Formula

**ICE = Impact × Confidence × Ease**

| Parameter | Scale |
|-----------|-------|
| **Impact** | 1-10 (how much this feature contributes to the module's star rating) |
| **Confidence** | 1-10 (how sure are we this will work as designed) |
| **Ease** | 1-10 (10 = trivial to build, 1 = extremely hard) |

### Example: Tasks & Reminders Module

| Feature | Impact | Confidence | Ease | ICE | Priority |
|---------|--------|------------|------|-----|----------|
| Set reminder via text | 10 | 10 | 8 | 800 | P0 |
| Morning brief with today's tasks | 9 | 8 | 7 | 504 | P0 |
| Recurring tasks | 7 | 9 | 6 | 378 | P0 |
| Natural language date parsing | 8 | 7 | 5 | 280 | P1 |
| Task completion tracking | 6 | 8 | 7 | 336 | P1 |
| Subtasks / checklists | 5 | 6 | 4 | 120 | P2 |
| Task delegation to contacts | 7 | 5 | 3 | 105 | P2 |
| Gamification / streaks | 3 | 3 | 5 | 45 | Won't Have |

---

## Trade-Off Template

When facing a scope trade-off, fill in this template:

```
**Trade-off:** [Option A] vs [Option B]

**Option A:** [Description]
- Star rating impact: [+X★]
- Effort: [X weeks]
- Risk: [Low/Med/High]

**Option B:** [Description]
- Star rating impact: [+X★]
- Effort: [X weeks]
- Risk: [Low/Med/High]

**Recommendation:** [A/B] because [reason tied to principles].

**What we lose:** [Honest assessment of what the other option offered]
```

---

## Monthly Re-Prioritization Process

On the first Monday of each month:

1. **Update Reach estimates** with actual usage data.
2. **Update Impact estimates** with user feedback and support tickets.
3. **Update Confidence** — anything validated moves to 80%+, anything disproven drops or gets removed.
4. **Recalculate RICE scores** and check if the phase order still holds.
5. **Review Won't Build list** — does anything deserve re-evaluation?
6. **Document changes** with reasoning in a changelog at the bottom of this file.

---

## Changelog

| Date | Change | Reasoning |
|------|--------|-----------|
| [YYYY-MM-DD] | Initial prioritization | Based on founding team assumptions and competitor analysis |
