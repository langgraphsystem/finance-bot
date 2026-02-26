# Project Roadmap

**Date:** 2026-02-25
**Updated:** 2026-02-26
**Status:** Active

## Completed (Phase 1-6 + Recent)

| What | When | Status |
|------|------|--------|
| Finance, Life-tracking, Research, Tasks, Writing, Email, Calendar, Shopping, Browser, CRM/Booking | before Feb 2026 | **DONE** — 68 base skills, 11 agents |
| Locale/Timezone vNext Phase 0-5 | Feb 2026 | **DONE** — migration, backfill, resolver, write path, dispatch, hardening |
| AI Data Tools (LLM function calling) | 25 Feb | **DONE** — 5 tools, 5 agents |
| Specialist Config Engine | 25 Feb | **DONE** — YAML-driven, manicure + flowers + construction |
| LangGraph upgrade (checkpointer + HITL + parallel Brief) | 25 Feb | **DONE** — 4 orchestrators (email, brief, booking, approval) |
| Universal Receptionist Skill | 25 Feb | **DONE** — config-driven business front desk (`fa87ed8`) |
| Hierarchical Supervisor Routing | 25 Feb | **DONE** — 2-level domain→intent, YAML skill catalog (`a5c235f`) |
| Wave 1 Financial Specialists | 25 Feb | **DONE** — financial_summary, generate_invoice, tax_estimate, cash_flow_forecast (`2195c06`) |
| Finance Specialist domain routing | 26 Feb | **DONE** — `Domain.finance_specialist` enum, correct agent routing (`f191faf`) |
| Dead code cleanup (hooks.py removed) | 26 Feb | **DONE** — removed orphaned 178-line hooks module |
| Multilingual booking parsing | 26 Feb | **DONE** — RU/ES error messages, improved parse prompt (`9e2cd96`) |

**Current totals: 74 skills, 12 agents, 4 LangGraph orchestrators, 1516 tests**

---

## Near-Term (March 2026)

### 1. Deep Agents (selective integration)

- `generate_program` complex path — planning + subagents + filesystem
- Tax reports — data collection → analysis → PDF
- Marketing campaigns — research → strategy → content
- Complexity classifier: simple → current path (4K tokens), complex → Deep Agent (80-150K tokens)
- DO NOT touch other 65+ skills — they remain Tier 1/2

---

## June-July 2026

### 7. Wave 2 — Marketing & Sales

| Specialist | Tier |
|-----------|------|
| Content Creator | Deep |
| Email Marketer | Workflow |
| Google/Meta Ads | Workflow |
| Sales Outreach | Workflow |
| Customer Support | Simple |
| SEO Specialist | Workflow |

### 8. Voice Receptionist

- Twilio/Vapi → STT (`gpt-4o-mini-transcribe`) → Message Bus → Agent → TTS → Voice response
- Unified module with text receptionist (different channel adapter, same logic)
- Voice-specific UX: pauses, repeat requests, hold music

### 9. Wave 3 — Verticals

| Specialist | Tier | Target Audience |
|-----------|------|----------------|
| Real Estate Agent | Workflow | Realtors — listings, virtual staging, lead follow-up |
| Beauty Salon | Workflow | Schedule, client booking, reminders, loyalty |
| Contractor/Plumber | Workflow | Estimates, scheduling, invoicing, route optimization |
| E-commerce/Amazon | Workflow | Product listing, PPC, ACOS, inventory |
| Restaurant/Food | Workflow | Menu, orders, inventory, food cost calculation |

---

## August+ 2026

### 10. Wave 4 — Lifestyle & Niche

Nutritionist, Fitness Trainer, Coach/Personal Growth, Tutor, Career Consultant, Legal Assistant, Recruiter, Property Manager, Travel Planner, Event Planner, Pet Business, Auto Repair

### 11. Vertical Packages (by business_type)

| Package | Specialists Included |
|---------|---------------------|
| **Freelancer** | Bookkeeper + Invoicing + Tax + Content Creator |
| **Beauty Salon** | Booking + Clients + Loyalty + Voice Receptionist |
| **Contractor** | Estimates + Scheduling + Invoicing + Route Optimization |
| **E-commerce** | Amazon/Shopify + Ads + Inventory + Analytics |
| **Real Estate** | Listings + Leads + Market Analysis + Follow-ups |
| **Restaurant** | Menu + Orders + Inventory + Food Cost |

### 12. Infrastructure (as scale grows)

- LangSmith Polly (when >15 agents)
- Mem0g graph memory
- Hybrid semantic search (BM25 + vector RRF)
- Dynamic few-shot examples (pgvector bank)
- Weekly digest push to user

---

## Cleanup (any time)

- [ ] Delete dead agent branches in GitHub
- [ ] Fix node_modules in Gemini branch
- [ ] Mini App frontend SPA (backend api/miniapp.py ready)
- [ ] CI auto-deploy (`RAILWAY_TOKEN` secret in GitHub)
- [x] ~~Locale vNext Phase 3-5~~ — DONE (Feb 2026)
- [x] ~~LangGraph integration~~ — DONE (4 orchestrators, Feb 2026)
- [x] ~~Remove hooks.py dead code~~ — DONE (26 Feb)

---

## Architecture Evolution

```
NOW:        Intent → Supervisor → 12 agents → 74 skills (2-level routing ready)

NEXT:       Intent → Supervisor → Domain Supervisors → 15+ agents → 80+ skills

TARGET:     Intent → Top Supervisor → 3 Domain Supervisors → 40+ agents → 200+ skills
                                       (Finance, Life, Business)
```

## Agent Tier System

| Tier | Type | Tokens | Latency | % of Requests |
|------|------|--------|---------|---------------|
| Tier 1 | Simple (1 LLM call) | 300-4K | 1-5 sec | ~80% |
| Tier 2 | Workflow (LangGraph) | 5-20K | 5-30 sec | ~15% |
| Tier 3 | Deep (Deep Agents) | 50-150K | 60-300 sec | ~5% |

## Revenue Strategy

| Tier | Price | Includes |
|------|-------|---------|
| **Base** | $49/mo | All current skills + Wave 1 specialists |
| **Pro** | $99/mo | All specialists + Deep Agent tasks + priority support |
| **Vertical** | Custom | Industry-specific packages |

---

## Key Metrics

| Metric | Current (74 skills) | After Wave 2 | After All Waves |
|--------|-------------------|--------------|-----------------|
| Skills | 74 | ~85 | 200+ |
| Agents | 12 | ~15 | 40+ |
| Orchestrators | 4 (email, brief, booking, approval) | 6+ | 10+ |
| Routing levels | 2 (supervisor ready) | 2 (supervisor active) | 3 (hierarchical) |
| Avg simple request tokens | ~1K | ~1.2K | ~1.5K |
| Avg complex request tokens | ~5K | ~15K | ~100K |
| Monthly LLM cost (1K users) | ~$200 | ~$350 | ~$600 |

---

## Related Plans

- `docs/plans/2026-02-25-comprehensive-integration-analysis.md` — Full technical analysis
- `docs/plans/2026-02-25-langgraph-langchain-integration-audit.md` — LangGraph audit (Codex)
- `docs/plans/2026-02-25-architecture-audit-vnext-language-timezone-reminders.md` — Locale vNext
- `docs/plans/2026-02-24-multi-agent-orchestrator-design.md` — Dev workflow design
