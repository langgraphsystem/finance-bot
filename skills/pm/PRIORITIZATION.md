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

### Phases 1-3 (Completed — v4.0)

| # | Module | Reach | Impact | Confidence | Effort (wks) | RICE Score | Phase | Status |
|---|--------|-------|--------|------------|--------------|------------|-------|--------|
| 1 | Onboarding | 100% | 3.0 | 90% | 3 | 90.0 | **Phase 1** | ✅ Done |
| 2 | Tasks & Reminders | 95% | 3.0 | 90% | 4 | 64.1 | **Phase 1** | ✅ Done |
| 3 | Research & Answers | 80% | 2.0 | 80% | 3 | 42.7 | **Phase 1** | ✅ Done |
| 4 | Writing Assistance | 70% | 2.0 | 80% | 3 | 37.3 | **Phase 1** | ✅ Done |
| 5 | Calendar Management | 90% | 2.0 | 85% | 5 | 30.6 | **Phase 1** | ✅ Done |
| 6 | Email Management | 65% | 2.0 | 70% | 6 | 15.2 | **Phase 2** | ✅ Done |
| 7 | Finance & Expenses | 55% | 2.0 | 60% | 5 | 13.2 | **Phase 2** | ✅ Done |
| 8 | Contacts & CRM | 50% | 1.0 | 50% | 4 | 6.3 | **Phase 2** | ✅ Done |
| 9 | Shopping & Orders | 45% | 1.0 | 40% | 6 | 3.0 | **Phase 3** | ✅ Done |
| 10 | Monitoring & Alerts | 40% | 1.0 | 50% | 5 | 4.0 | **Phase 3** | ✅ Done |
| 11 | Browser Automation | 35% | 1.0 | 60% | 4 | 5.3 | **Phase 3** | ✅ Done |
| 12 | Booking & CRM | 50% | 1.0 | 50% | 4 | 6.3 | **Phase 3** | ✅ Done |

### Phases 7-9 (Planned — v5.0+)

| # | Module | Reach | Impact | Confidence | Effort (wks) | RICE Score | Phase | PRD |
|---|--------|-------|--------|------------|--------------|------------|-------|-----|
| 14 | YAML Prompt Migration | 100% | 1.0 | 90% | 2 | 45.0 | **Phase 7** | `intelligence-export.md` |
| 15 | Hybrid Semantic Search | 80% | 2.0 | 80% | 3 | 42.7 | **Phase 7** | `intelligence-export.md` |
| 16 | Weekly Digest | 90% | 2.0 | 85% | 2 | 76.5 | **Phase 7** | `intelligence-export.md` |
| 17 | Excel Export | 70% | 2.0 | 80% | 2 | 56.0 | **Phase 7** | `intelligence-export.md` |
| 18 | Dynamic Few-shot Examples | 80% | 2.0 | 70% | 3 | 37.3 | **Phase 7** | `intelligence-export.md` |
| 19 | Google Sheets Sync | 40% | 2.0 | 60% | 3 | 16.0 | **Phase 7** | `intelligence-export.md` |
| 20 | Schedule C + Auto-Deductions | 55% | 3.0 | 70% | 4 | 28.9 | **Phase 8** | `financial-pro.md` |
| 21 | Invoice Tracking | 50% | 3.0 | 80% | 5 | 24.0 | **Phase 8** | `financial-pro.md` |
| 22 | Accountant Read-Only Access | 40% | 2.0 | 70% | 3 | 18.7 | **Phase 8** | `financial-pro.md` |
| 23 | IFTA Export | 15% | 2.0 | 60% | 3 | 6.0 | **Phase 8** | `financial-pro.md` |
| 24 | Per Diem Tracking | 25% | 1.0 | 50% | 2 | 6.3 | **Phase 8** | `financial-pro.md` |
| 25 | Voice Message Processing | 70% | 2.0 | 80% | 3 | 37.3 | **Phase 9** | `platform-evolution.md` |
| 26 | Mini App Frontend SPA | 80% | 2.0 | 70% | 6 | 18.7 | **Phase 9** | `platform-evolution.md` |
| 27 | Graph Memory (Mem0g) | 60% | 2.0 | 50% | 5 | 12.0 | **Phase 9** | `platform-evolution.md` |
| 28 | AI-Generated YAML Profiles | 100% | 1.0 | 50% | 3 | 16.7 | **Phase 9** | `platform-evolution.md` |
| 29 | Telegram Stars Monetization | 30% | 1.0 | 40% | 3 | 4.0 | **Phase 9** | `platform-evolution.md` |

### Deferred (Confidence < 50% — validate first)

| # | Module | Reach | Impact | Confidence | Effort (wks) | RICE Score | Notes |
|---|--------|-------|--------|------------|--------------|------------|-------|
| 30 | Voice Calls (phone-based) | 20% | 0.5 | 30% | 8 | 0.4 | Extremely hard. Wait for API maturity. |
| 31 | Social & Reviews | 30% | 1.0 | 40% | 4 | 3.0 | Niche. Validate with business users first. |
| 32 | Health & Wellness | 35% | 1.0 | 30% | 5 | 2.1 | Sensitive domain. Run user survey first. |
| 33 | Bank Sync (Plaid) | 60% | 2.0 | 40% | 6 | 8.0 | High regulatory risk. Validate compliance path. |
| 34 | Accounting Software Sync | 30% | 2.0 | 30% | 5 | 3.6 | QuickBooks/Xero APIs complex. Wait for demand signal. |

---

## Phase Breakdown

### Phases 1-6 — Completed (v4.0) ✅

All MVP and expansion phases are shipped. 67 skills, 11 agents, 4 channels, 2 LangGraph orchestrators. Star rating: 6★.

See `IMPLEMENTATION_PLAN.md` for full details on Phases 0-6.

### Phase 7 — Intelligence & Export

**Goal:** Smarter intent detection, better context retrieval, data portability. Move from 6★ to 7★.

| Module | Why Phase 7 |
|--------|-------------|
| Weekly Digest | RICE 76.5 — Highest value quick win. 90% reach, proactive, cross-domain. Sunday summary drives re-engagement. |
| Excel Export | RICE 56.0 — Unlocks professional use. David's accountant needs spreadsheets, not chat screenshots. |
| YAML Prompt Migration | RICE 45.0 — Developer velocity. 51 skills with hardcoded prompts slow iteration. Unblocks A/B testing. |
| Hybrid Semantic Search | RICE 42.7 — Foundation for 7★. Better context retrieval = better responses across all skills. |
| Dynamic Few-shot Examples | RICE 37.3 — Intent accuracy improves from ~85% to 92%+. Every user benefits from fewer misclassifications. |
| Google Sheets Sync | RICE 16.0 — Business users share data with accountants/spouses. Lower reach but high retention impact. |

**Phase 7 success metric:** Intent accuracy > 92%. Weekly digest open rate > 50%. 100+ Excel exports in first month.

**PRD:** `docs/prds/intelligence-export.md`

### Phase 8 — Financial Pro

**Goal:** Tax-aware finance, invoicing, professional access. Move from 7★ to 8★ for business users.

| Module | Why Phase 8 |
|--------|-------------|
| Schedule C + Auto-Deductions | RICE 28.9 — 41M self-employed Americans need this. High impact, validated need, moderate confidence. |
| Invoice Tracking | RICE 24.0 — Service businesses (David) send 2-3 invoices daily. Automates a painful manual workflow. |
| Accountant Read-Only Access | RICE 18.7 — Bridges the bot and professional accounting. Reduces churn for business users. |
| IFTA Export | RICE 6.0 — Niche (truckers, plumbers with vehicles) but high impact for those users. Strong word-of-mouth. |
| Per Diem Tracking | RICE 6.3 — Low effort quick win. IRS rates are public data. Calendar integration already exists. |

**Phase 8 success metric:** 40%+ of self-employed users enable Schedule C tracking. 4+ invoices/month per business user.

**PRD:** `docs/prds/financial-pro.md`

### Phase 9 — Platform Evolution

**Goal:** Multi-modal input/output, relational memory, monetization. Move from 8★ to 9★.

| Module | Why Phase 9 |
|--------|-------------|
| Voice Message Processing | RICE 37.3 — 70% of users send voice messages. Unlocks on-the-go usage for drivers, parents, field workers. |
| Mini App Frontend SPA | RICE 18.7 — Visual output (charts, dashboards) that text can't deliver. Backend already built (40K lines). |
| AI-Generated YAML Profiles | RICE 16.7 — 100% of new users benefit. Reduces time-to-personalization from 3 weeks to 3 days. |
| Graph Memory (Mem0g) | RICE 12.0 — "Who is Emma's dentist?" requires relational understanding. Enables 8★+ cross-domain intelligence. |
| Telegram Stars Monetization | RICE 4.0 — Supplementary revenue via in-app purchases. Premium reports, advanced analytics. |

**Phase 9 success metric:** 25%+ users send voice messages. Mini App opens 2x/week. Graph memory accuracy > 90%.

**PRD:** `docs/prds/platform-evolution.md`

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
| Native mobile app | Mini App (Phase 9) covers visual needs. Full native app adds maintenance without proportional value. |
| Dashboard / web portal | Mini App is the visual layer. Separate web portal fragments the experience. |
| Multi-language support (at launch) | Focus on English + Spanish for US market. Internationalization revisit at 10K users. |
| Team collaboration (shared bots) | Individual assistant first. Team features are a different product with different economics. |
| Smart home integration | Alexa/Google Home control is niche, unreliable, and has strong incumbents. Not our fight. |
| Crypto / stock trading | Regulatory minefield. Financial tracking (yes), trading (no). |
| iMessage integration | Apple provides no public API. BlueBubbles requires dedicated macOS machine. Not viable. |
| Automated tax filing | Regulatory risk. We prepare data (Schedule C, IFTA). Humans file taxes. |
| Payroll / W-2 / 1099 | Separate regulated domain with heavy compliance requirements. |
| Bank sync (Plaid) at launch | High regulatory risk, complex compliance. Deferred until demand validated and compliance path confirmed. |
| GPS mileage tracking | Requires mobile app or background location. Violates conversation-first principle. IRS simplified method available. |
| Real-time voice transcription | Telegram sends completed voice messages. Streaming adds complexity without benefit. Batch processing is sufficient. |

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
| 2025-01-01 | Initial prioritization | Based on founding team assumptions and competitor analysis |
| 2026-02-23 | Phases 1-6 marked complete. Added 16 new modules for Phases 7-9. Updated Won't Build list. Added Deferred section. | All v4.0 phases shipped. New priorities based on gap analysis: intelligence (search, few-shot), export (Excel, Sheets), financial pro (tax, invoicing, accountant access), platform evolution (voice, Mini App, graph memory). Deferred low-confidence modules (voice calls, social, health, bank sync) pending validation. |
