# Project Roadmap

**Date:** 2026-02-25
**Status:** Active

## Completed (Phase 1-6 + Recent)

| What | When | Status |
|------|------|--------|
| Finance, Life-tracking, Research, Tasks, Writing, Email, Calendar, Shopping, Browser, CRM/Booking | before Feb 2026 | **DONE** — 68 skills, 11 agents |
| Locale/Timezone vNext Phase 0-1 | Feb 2026 | **DONE** — migration, backfill, telemetry |
| Locale vNext Phase 2 (read path) | Feb 2026 | **PARTIAL** — reminders/life done, proactivity not yet |
| AI Data Tools (LLM function calling) | 25 Feb | **DONE** — 5 tools, 5 agents |
| Specialist Config Engine | 25 Feb | **DONE** — YAML-driven, manicure + flowers |

---

## Near-Term (March 2026)

### 1. Locale/Timezone — Close Out (1 week)

- Phase 2: connect locale resolver in proactivity tasks
- Phase 3: normalize write path (onboarding, settings)
- Phase 4: unify dispatch (single template service)
- Phase 5: hardening + cleanup

Details: `docs/plans/2026-02-25-architecture-audit-vnext-language-timezone-reminders.md`

### 2. LangGraph Integration (2 weeks)

- `langgraph-checkpoint-postgres` — durable state for email/brief graphs
- `interrupt()` / `resume()` — replace `pending_actions.py` (Redis → LangGraph HITL)
- Deferred Nodes — Brief collectors in parallel (currently sequential)
- Node Caching — Brief collectors 60s cache
- Feature flags: `FF_LANGGRAPH_BOOKING_V1`, `FF_LANGGRAPH_PENDING_ACTIONS_V1`, `FF_LANGGRAPH_EMAIL_V2`, `FF_LANGGRAPH_BRIEF_PARALLEL_V2`

Details: `docs/plans/2026-02-25-langgraph-langchain-integration-audit.md`

### 3. Universal Receptionist Skill — **DONE** (`fa87ed8`)

- Single `receptionist` skill, adaptable via specialist config
- Integration with existing booking/contacts skills
- Added specialist config to construction.yaml (3 profiles now configured)
- Config-driven system prompts per business_type

---

## Mid-Term (April-May 2026)

### 4. Hierarchical Supervisor — **DONE** (`a5c235f`)

- Supervisor routing, scoped intent detection, pre/post model hooks
- Progressive Skill Loading via YAML catalog
- Feature flag `ff_supervisor_routing`

### 5. Wave 1 Specialists — **DONE** (`2195c06`)

| Specialist | Tier | What Already Exists |
|-----------|------|-------------------|
| **Bookkeeper** | Workflow | transactions, categories, budgets |
| **Invoicing** | Workflow | contacts + transactions → PDF generation |
| **Tax Consultant** | Deep | transactions → Schedule C, deductions, quarterly estimates |
| **Cash Flow Forecast** | Workflow | historical data → trend analysis → prediction |

### 6. Deep Agents (selective integration)

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

- [ ] Delete 5 dead agent branches in GitHub
- [ ] Fix node_modules in Gemini branch
- [ ] Locale vNext Phase 3-5 (close out)
- [ ] Mini App frontend SPA (backend api/miniapp.py ready)
- [ ] CI auto-deploy (`RAILWAY_TOKEN` secret in GitHub)

---

## Architecture Evolution

```
NOW:        Intent → 11 agents → 68 skills (flat)

PHASE 2:    Intent → Supervisor → Domain Supervisors → 15+ agents → 80+ skills

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

| Metric | Current (68 skills) | After Phase 2 | After All Waves |
|--------|-------------------|--------------|-----------------|
| Skills | 68 | ~80 | 200+ |
| Agents | 11 | ~15 | 40+ |
| Orchestrators | 2 (email, brief) | 5+ | 10+ |
| Routing levels | 1 (flat) | 2 (supervisor) | 3 (hierarchical) |
| Avg simple request tokens | ~1K | ~1.2K | ~1.5K |
| Avg complex request tokens | ~5K | ~15K | ~100K |
| Monthly LLM cost (1K users) | ~$200 | ~$350 | ~$600 |

---

## Related Plans

- `docs/plans/2026-02-25-comprehensive-integration-analysis.md` — Full technical analysis
- `docs/plans/2026-02-25-langgraph-langchain-integration-audit.md` — LangGraph audit (Codex)
- `docs/plans/2026-02-25-architecture-audit-vnext-language-timezone-reminders.md` — Locale vNext
- `docs/plans/2026-02-24-multi-agent-orchestrator-design.md` — Dev workflow design
