# PRD: Universal Receptionist Skill

**Date:** 2026-02-26
**Author:** Claude Code
**Star Rating:** 6★ (MVP — config-driven front desk, answers business questions, guides to booking)
**Score:** 26/30

## Problem

Business owners (David — plumber, manicure salons, flower shops) need a single skill that acts as their "front desk": answering questions about services, prices, hours, and availability. Today the specialist config injects knowledge into the booking agent's system prompt, but there's no dedicated skill for business inquiries that don't involve creating a booking. A client asking "how much for a sink repair?" or "are you open Saturday?" gets routed to general_chat instead of using the rich specialist YAML config.

## User Stories

### David (Queens plumber)
- "What services do I offer?" → sees his full service list with prices
- "Am I open on Saturday?" → checks working hours from config
- "What should I charge for a kitchen remodel?" → uses specialist pricing data
- "Show me my FAQ" → displays business FAQ from config

### Maria (Brooklyn mom — household profile)
- Receptionist skill gracefully declines: "This works for business profiles. You're set up as household."

### Manicure salon owner
- "Какие у меня услуги?" → shows service list in Russian with prices
- "Во сколько мы закрываемся в субботу?" → "В 18:00"
- Client asks about gel nails → receptionist drafts a response using FAQ

## Solution

Single `receptionist` skill that:
1. Reads `context.profile_config.specialist` for all business knowledge
2. Answers questions about services, pricing, working hours, availability
3. Shows interactive buttons for common actions (view services, book, FAQ)
4. Handles FAQ lookups from YAML config
5. Checks real-time availability against working hours
6. Falls back gracefully when no specialist config exists

## Technical Design

### New Files
- `src/skills/receptionist/__init__.py`
- `src/skills/receptionist/handler.py`

### Modified Files
- `src/core/intent.py` — add `receptionist` intent
- `src/core/domains.py` — map to `Domain.booking`
- `src/skills/__init__.py` — register skill
- `src/agents/config.py` — add to booking agent skills
- `src/core/memory/context.py` — add QUERY_CONTEXT_MAP entry
- `config/skill_catalog.yaml` — add triggers
- `config/profiles/construction.yaml` — add specialist section

### Intent
`receptionist` — "what services do you offer?", "are you open Saturday?", "how much is X?", "часы работы", "какие услуги"

### Agent Assignment
Added to `booking` agent (already has specialist knowledge injection). No new agent needed.

## Success Metrics
- Business profiles with specialist config get contextual responses (not generic)
- Service/price/hours questions answered from YAML (zero LLM hallucination on structured data)
- Non-business profiles get graceful fallback

## Scope
- IN: Service list, pricing, hours, FAQ, availability check, basic buttons
- OUT: Automated client-facing chatbot mode, voice receptionist, appointment conflict resolution

## Risks
- Intent overlap with `create_booking` or `quick_answer` → mitigated by priority rules in intent prompt
- Profiles without specialist config → graceful "not configured" message

## Self-Score

| Criteria | Score | Notes |
|----------|-------|-------|
| Problem Clarity | 5 | Clear gap: specialist data exists, no skill uses it for inquiries |
| User Stories | 4 | David and salon owner covered; Maria graceful fallback |
| Success Metrics | 4 | Measurable: correct answers from config, no hallucination |
| Scope Definition | 5 | Clear IN/OUT boundary |
| Technical Feasibility | 4 | Builds on existing specialist infrastructure |
| Risk Assessment | 4 | Intent overlap addressed with priority rules |
| **Total** | **26/30** | Ready to build |
