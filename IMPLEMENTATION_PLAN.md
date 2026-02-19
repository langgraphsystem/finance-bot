# AI Life Assistant — Implementation Plan

## Version: 4.0 | Date: 2026-02-19

**Approach**: 100% Python — no TypeScript sidecar, no external orchestration frameworks for channel management
**Base**: Existing Finance Bot codebase (383 Python files, 61 skills, 11 agents, deployed on Railway + Supabase)
**New in v4.0**: All planned phases (0–6) implemented. Shopping lists, multi-channel gateways (Slack/WhatsApp/SMS), Stripe billing, LangGraph orchestrators (email/brief), browser automation, CRM/booking, proactivity engine, maps/youtube with Gemini Search Grounding. PRD: `docs/prds/platform-architecture.md`

---

## TABLE OF CONTENTS

1. [Current State](#1-current-state)
2. [Target State](#2-target-state)
3. [Architecture Decisions](#3-architecture-decisions)
4. [Phase Overview](#4-phase-overview)
5. [Phase 0: Bug Fixes](#5-phase-0-bug-fixes) ✅
6. [Phase 1: Core Generalization](#6-phase-1-core-generalization-weeks-1-2) ✅
7. [Phase 2: Email + Calendar](#7-phase-2-email--calendar-weeks-3-4) ✅
8. [Phase 3: Tasks + Research + Writing + CRM](#8-phase-3-tasks--research--writing--crm-weeks-5-6) ✅
9. [Phase 3.5: Platform Architecture](#9-phase-35-platform-architecture-weeks-7-8) ✅
10. [Phase 4: Channels + Billing](#10-phase-4-channels--billing-weeks-9-10) ✅
11. [Phase 5: Proactivity + Browser Automation + Polish](#11-phase-5-proactivity--browser-automation--polish-weeks-11-12) ✅
12. [Phase 6: Booking + CRM](#12-phase-6-booking--crm) ✅
13. [File-by-File Change Map](#13-file-by-file-change-map)
14. [Risk Register](#14-risk-register)
15. [Final Metrics](#15-final-metrics)
16. [What's Next](#16-whats-next)

---

## 1. CURRENT STATE (as of v4.0 — 2026-02-19)

```
Codebase:       383 Python files (255 src, 123 tests, 5 api)
Skills:         61 (14 finance + 8 life + 5 research + 4 tasks + 4 shopping + 4 writing
                    + 5 email + 5 calendar + 4 browser/monitor + 1 brief + 8 CRM/booking)
Agents:         11 (receipt, analytics, chat, onboarding, life, tasks, research, writing,
                    email, calendar, booking)
Orchestrators:  2 active LangGraph (email compose+review, brief collector+synthesizer)
DB Tables:      28 (SQLAlchemy 2.0 async + asyncpg, 7 Alembic migrations)
Channels:       4 (Telegram primary + Slack, WhatsApp, SMS implemented)
Tests:          123 test files (~948 tests)
Deploy:         Railway + Supabase (PostgreSQL + pgvector)
Packages:       ~256 managed with uv
CI/CD:          GitHub Actions (lint → test → docker → Railway deploy)
Billing:        Stripe ($49/month subscription)
```

### Phases Completed

| Phase | Status | Key Deliverables |
|-------|--------|-----------------|
| Phase 0 | ✅ Done | 7 bug fixes |
| Phase 1 | ✅ Done | Domain router, 2-stage intent, 8 new DB models, gateway abstraction |
| Phase 2 | ✅ Done | 10 email/calendar skills, OAuth model, crypto module, LangGraph email orchestrator |
| Phase 3 | ✅ Done | 13 task/research/writing skills, Gemini Search Grounding for web/maps/youtube |
| Phase 3.5 | ✅ Done | Shopping lists (4 skills), evening recap, connector + plugin architecture |
| Phase 4 | ✅ Done | Slack/WhatsApp/SMS gateways, Stripe billing, channel_links table |
| Phase 5 | ✅ Done | Browser automation (web_action, price_check), monitors (price_alert, news_monitor), proactivity |
| Phase 6 | ✅ Done | Booking/CRM (8 skills): contacts, bookings, client interactions, send_to_client |

### Known Gaps (resolved)

All previously identified gaps from Phases 0–3 have been addressed:
- ~~Email/Calendar stubs~~ → Real Gmail/Calendar API integration via OAuth + aiogoogle
- ~~Morning brief hallucinates~~ → LangGraph BriefOrchestrator with parallel fan-out collectors
- ~~No connector abstraction~~ → ConnectorRegistry with BaseConnector protocol
- ~~Maps/YouTube no API~~ → Dual-mode: Gemini Search Grounding (quick) + REST API (detailed)

### Model Routing (current)

| Model | ID | Role |
|-------|-----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Analytics, reports, onboarding, writing, email |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Chat, skills, calendar, tasks, fallback |
| GPT-5.2 | `gpt-5.2` | Fallback (analytics, OCR, complex) |
| Gemini 3 Flash | `gemini-3-flash-preview` | Intent detection, OCR, summarization, web search grounding |
| Gemini 3 Pro | `gemini-3-pro-preview` | Deep reasoning, complex analysis |

### Current Skills (61)

**Finance (14):** add_expense, add_income, scan_receipt, scan_document, query_stats, query_report, complex_query, onboarding, general_chat, correct_category, undo_last, set_budget, add_recurring, mark_paid

**Life-tracking (8):** quick_capture, track_food, track_drink, mood_checkin, day_plan, day_reflection, life_search, set_comm_mode

**Tasks (4):** create_task, list_tasks, set_reminder, complete_task

**Research (5):** web_search, quick_answer, compare_options, maps_search, youtube_search

**Writing (4):** draft_message, translate_text, write_post, proofread

**Email (5):** read_inbox, send_email, draft_reply, follow_up_email, summarize_thread

**Calendar (5):** list_events, create_event, find_free_slots, reschedule_event, morning_brief

**Shopping (4):** shopping_list_add, shopping_list_view, shopping_list_remove, shopping_list_clear

**Browser + Monitor (4):** web_action, price_check, price_alert, news_monitor

**Proactive (1):** evening_recap

**Booking + CRM (8):** add_contact, list_contacts, find_contact, create_booking, list_bookings, cancel_booking, reschedule_booking, send_to_client

*(1 skill — scan_document — is registered but not counted separately as it shares intents with scan_receipt)*

---

## 2. TARGET STATE (achieved as of v4.0)

```
Product:        AI Life Assistant ($49/month)
Market:         US consumers and small business owners
Interface:      Conversation-first — Telegram primary, Slack/WhatsApp/SMS secondary, Mini App SPA (backend ready)
Skills:         61 registered (across 10 domains)
Agents:         11 (receipt, analytics, chat, onboarding, life, tasks, research, writing, email, calendar, booking)
Orchestrators:  2 active LangGraph (EmailOrchestrator, BriefOrchestrator)
DB Tables:      28 (SQLAlchemy 2.0 async + asyncpg, 7 Alembic migrations)
Channels:       4 (Telegram primary + Slack, WhatsApp, SMS gateways implemented)
Architecture:   DomainRouter → AgentRouter → skill.execute(), LangGraph for complex flows
Billing:        Stripe ($49/month subscription)
Cost target:    $3-8/month API cost per user
Star rating:    6★ MVP (per 11_STAR_EXPERIENCE.md)
```

### Test Personas

Every feature decision is validated against two personas (see `skills/pm/PM_SKILL.md`):

- **Maria** — Brooklyn mom, 2 kids (Emma 8, Noah 5). School schedules, doctors, groceries, meal planning, family calendar. Needs: one morning message that covers her whole day.
- **David** — Queens plumber, 5 employees (Mike, Jose, Alex + 2). Job scheduling, client follow-ups, invoices, supply orders, Google reviews. Needs: business-specific categories (Materials, Vehicle, Subcontractor), morning brief with jobs + invoices + emails.

---

## 3. ARCHITECTURE DECISIONS

Key technical decisions based on research, with rationale.

### 3.1 No OpenClaw dependency

**Decision:** Build all channel integrations in Python directly.

**Why:** OpenClaw has 512 known vulnerabilities (Snyk/OSV), its plugin marketplace (ClawHub) suffered 341 malicious skill uploads, the project's founder left for OpenAI, and there is no dedicated security team. Using it for a customer-facing SaaS handling email, calendar, and financial data is an unacceptable risk.

**Instead:**
- Slack → `slack-bolt` (official Slack Python SDK, actively maintained)
- WhatsApp → WhatsApp Business Cloud API via `httpx` (Meta-hosted, no phone needed)
- SMS → Twilio Python SDK
- iMessage → Deferred indefinitely (Apple provides no public API)

### 3.2 `aiogoogle` for Google APIs (not `google-api-python-client`)

**Decision:** Use `aiogoogle` for Gmail + Calendar integration.

**Why:** Native async support (our entire codebase is async), lighter weight, better fits our FastAPI/asyncpg stack. The official `google-api-python-client` is synchronous and requires `run_in_executor()` wrapping.

**Cost:** $0/user — Google APIs are free for per-user OAuth access. No third-party API aggregator needed (Nylas $15+/mo, Composio $29+/mo, Nango $50+/mo all rejected as over-budget).

### 3.3 Internal PostgreSQL for Tasks (not Google Tasks API)

**Decision:** Store tasks in our own `tasks` table.

**Why:** Google Tasks API is too limited — no priorities, no assignment, no custom fields, no recurring tasks. Our internal table supports all features and keeps data under our control with RLS.

### 3.4 DomainRouter over AgentRouter (not LangGraph for everything)

**Decision:** Wrap existing `AgentRouter` with a `DomainRouter`. Use LangGraph only for complex multi-step domains with conditional branching and revision loops.

**Why:** 80% of the architecture is already built. Simple CRUD domains don't need graph-based orchestration. The DomainRouter is a thin wrapper that routes by domain, delegating to either a LangGraph orchestrator (for complex flows) or the existing AgentRouter (for simple flows).

**LangGraph domains (4):** email, research, writing, browser automation — these have multi-step workflows with branching, revision loops, and human-in-the-loop approval.

**skill.execute() domains (6):** finance, life-tracking, calendar, tasks, contacts, monitor — these are linear CRUD operations or cron-driven tasks.

### 3.5 2-stage intent detection

**Decision:** When intents exceed ~25, split into domain classification (Stage 1) → intent detection within domain (Stage 2).

**Why:** Gemini Flash accuracy degrades with >25 options in a single classification prompt. Two-stage keeps each prompt focused: Stage 1 classifies into ~12 domains, Stage 2 classifies into ~5-8 intents within that domain. Latency adds ~80ms but accuracy stays >95%.

### 3.6 Browser-Use for AI browser automation (Phase 5+)

**Decision:** Use Browser-Use library for browser automation tasks.

**Why:** 77K GitHub stars, MIT license, Python-native, 89.1% on WebVoyager benchmark. Combined with Steel.dev for isolated Chrome containers in production. Deferred to Phase 5 because it requires the rest of the system to be stable first.

### 3.7 Per-user Google OAuth

**Decision:** Each user authorizes their own Gmail + Calendar via OAuth 2.0 through a Telegram deep link flow.

**Flow:**
1. User says "connect my email" → bot generates unique state token
2. Bot sends deep link: `https://our-api.com/oauth/google/start?state=TOKEN`
3. User clicks → Google consent screen → grants Gmail + Calendar scopes
4. Callback exchanges code for tokens → encrypted storage in `oauth_tokens` table
5. Tokens auto-refresh via `aiogoogle` before expiry

### 3.8 Declarative YAML Prompts (inspired by Cowork SKILL.md pattern)

**Decision:** Externalize system prompts into `prompts.yaml` files alongside each skill handler.

**Why:** Cowork's plugin architecture proves that SKILL.md files with frontmatter metadata are sufficient for skill definition. Our version uses YAML instead of Markdown (structured data > free text for programmatic access). This enables: (1) prompt iteration without code deployment, (2) PM/copywriter access to bot voice, (3) future auto-discovery of skills from YAML metadata, (4) A/B prompt testing via `variants` field.

**Migration:** Gradual — skills without `prompts.yaml` fall back to hardcoded prompts. No breaking change.

### 3.9 Connector Registry (inspired by Cowork MCP/.mcp.json pattern)

**Decision:** Build a unified `ConnectorRegistry` with `BaseConnector` protocol for all external services.

**Why:** Cowork's `.mcp.json` pattern proves declarative service configuration works. Our connectors handle OAuth lifecycle (connect/disconnect/refresh), provide `get_client()` for ready-to-use API clients, and centralize error handling. Skills never import API libraries directly — they request a client from the registry. This makes Phase 4 channels trivial to add.

**Not MCP:** We don't use MCP protocol itself — it's designed for LLM tool calling, not for our skill-based architecture. We take the pattern (declarative config + protocol-based connectors) but implement it as native Python.

### 3.10 Plugin Bundles for Business Profiles (inspired by Cowork plugins)

**Decision:** Extend `config/profiles/*.yaml` into self-contained plugin bundles with prompt overrides, custom categories, report templates, and configurable morning brief sections.

**Why:** Cowork's plugin architecture (manifest + skills + commands in a folder) maps directly to our business profile needs. A plumber and a restaurant owner need different expense categories, different report formats, and different morning brief sections. Plugin bundles make this customization file-based, not code-based.

### 3.11 Multi-Agent Orchestrator for Cross-Domain Queries

**Decision:** Build orchestrator skills that call multiple sub-skills in parallel via `asyncio.gather()`, then synthesize results with a single LLM call.

**Why:** Inspired by Cowork's sub-agent coordination pattern and Agent Teams' lead+teammates model. Our `morning_brief` currently hallucinates because it can't access data from calendar, tasks, email, and finance simultaneously. An orchestrator skill collects data from domain-specific skills in parallel (3s timeout each), then Claude Sonnet synthesizes a coherent brief.

**Not LangGraph:** This is simpler than LangGraph — no conditional edges, no state machine. Pure `asyncio.gather()` + LLM synthesis. LangGraph stays for genuinely complex multi-step flows (email drafting with revision loops, browser automation).

### 3.12 Progressive Context Disclosure

**Decision:** Dynamically reduce context loading for simple queries using regex heuristics.

**Why:** Currently every `add_expense` loads Mem0 merchant mappings + 3 history messages, even for "100р кофе." Cowork's progressive disclosure pattern (metadata first → full instructions → resources on demand) validates lazy loading. Our heuristic detects simple messages (regex patterns for amounts, confirmations, greetings) and skips heavy context layers. Conservative default: if unsure, load everything.

**No LLM gating:** For now, purely regex-based. LLM-based complexity assessment deferred to Phase 5 (adds latency + cost that defeats the purpose for simple queries).

---

## 4. PHASE OVERVIEW

```
Phase 0 (pre)       │ ✅ Done     │ Fix 7 bugs in current codebase
Phase 1 (wk 1-2)    │ ✅ Done     │ Generalize core: domain router, 2-stage intent, new DB tables
Phase 2 (wk 3-4)    │ ✅ Done     │ Email + Calendar skills + OAuth model + crypto + LangGraph orchestrators
Phase 3 (wk 5-6)    │ ✅ Done     │ Tasks + Research + Writing + CRM skills + Gemini Search Grounding
Phase 3.5 (wk 7-8)  │ ✅ Done     │ Shopping lists, evening recap, connectors, plugins, smart context
Phase 4 (wk 9-10)   │ ✅ Done     │ Slack, WhatsApp, SMS gateways + Stripe billing + channel_links
Phase 5 (wk 11-12)  │ ✅ Done     │ Browser automation, price/news monitors, proactivity engine
Phase 6 (wk 13-14)  │ ✅ Done     │ Booking/CRM: contacts, bookings, client interactions, send_to_client
```

### Implementation Notes

- **Phase 3.5** added shopping list skills (4) and evening_recap, plus the connector/plugin foundation
- **Phase 4** implemented 3 channel gateways and Stripe $49/month subscription billing
- **Phase 5** added 4 browser/monitor skills (web_action, price_check, price_alert, news_monitor)
- **Phase 6** added 8 CRM/booking skills with bookings + client_interactions tables (Alembic migration 007)
- **Maps/YouTube** (added in Phase 3 area): dual-mode architecture with Gemini Search Grounding (quick) + direct REST API (detailed). YouTube also supports URL analysis via Gemini grounding

---

## 5. PHASE 0: BUG FIXES

Fix before any new development. All changes are in 2 files.

| # | Bug | File | Fix |
|---|-----|------|-----|
| 1 | `query_report` skill not assigned to any agent | `src/agents/config.py:65` | Add `"query_report"` to analytics agent's skills list |
| 2 | `mark_paid` missing from QUERY_CONTEXT_MAP | `src/core/memory/context.py` | Add entry: `{"mem": False, "hist": 3, "sql": False, "sum": False}` |
| 3 | `set_budget` missing from QUERY_CONTEXT_MAP | `src/core/memory/context.py` | Add entry: `{"mem": "budgets", "hist": 3, "sql": True, "sum": False}` |
| 4 | `add_recurring` missing from QUERY_CONTEXT_MAP | `src/core/memory/context.py` | Add entry: `{"mem": "mappings", "hist": 3, "sql": False, "sum": False}` |
| 5 | `scan_document` missing from QUERY_CONTEXT_MAP | `src/core/memory/context.py` | Add entry: `{"mem": "mappings", "hist": 1, "sql": False, "sum": False}` |
| 6 | Dead `budget_advice` entry in QUERY_CONTEXT_MAP | `src/core/memory/context.py:60` | Remove line |
| 7 | Duplicate `correct_cat` alias in QUERY_CONTEXT_MAP | `src/core/memory/context.py:56` | Remove `correct_cat` (keep only `correct_category`) |

---

## 6. PHASE 1: CORE GENERALIZATION (Weeks 1-2)

### 6.1 Introduce domain concept

The core architectural change: intents get a `domain` for routing. Current finance intents remain backward-compatible.

#### 6.1.1 New file: `src/core/domains.py`

```python
"""Domain definitions for multi-domain routing."""

from enum import StrEnum


class Domain(StrEnum):
    finance = "finance"
    email = "email"
    calendar = "calendar"
    tasks = "tasks"
    research = "research"
    writing = "writing"
    contacts = "contacts"
    web = "web"
    social = "social"
    monitor = "monitor"
    general = "general"
    onboarding = "onboarding"


# Maps each intent to its domain
INTENT_DOMAIN_MAP: dict[str, Domain] = {
    # Finance (existing 14 intents)
    "add_expense":      Domain.finance,
    "add_income":       Domain.finance,
    "scan_receipt":     Domain.finance,
    "scan_document":    Domain.finance,
    "query_stats":      Domain.finance,
    "query_report":     Domain.finance,
    "correct_category": Domain.finance,
    "undo_last":        Domain.finance,
    "mark_paid":        Domain.finance,
    "set_budget":       Domain.finance,
    "add_recurring":    Domain.finance,
    "complex_query":    Domain.finance,

    # Life (existing 8 intents)
    "quick_capture":    Domain.general,
    "track_food":       Domain.general,
    "track_drink":      Domain.general,
    "mood_checkin":     Domain.general,
    "day_plan":         Domain.tasks,
    "day_reflection":   Domain.general,
    "life_search":      Domain.general,
    "set_comm_mode":    Domain.general,

    # Email (new — Phase 2)
    "read_inbox":       Domain.email,
    "send_email":       Domain.email,
    "draft_reply":      Domain.email,
    "follow_up_email":  Domain.email,
    "summarize_thread": Domain.email,

    # Calendar (new — Phase 2)
    "list_events":      Domain.calendar,
    "create_event":     Domain.calendar,
    "find_free_slots":  Domain.calendar,
    "reschedule_event": Domain.calendar,
    "morning_brief":    Domain.calendar,

    # Tasks (new — Phase 3)
    "create_task":      Domain.tasks,
    "list_tasks":       Domain.tasks,
    "set_reminder":     Domain.tasks,
    "complete_task":    Domain.tasks,

    # Research (new — Phase 3)
    "web_search":       Domain.research,
    "deep_research":    Domain.research,
    "compare_options":  Domain.research,

    # Writing (new — Phase 3)
    "draft_message":    Domain.writing,
    "translate_text":   Domain.writing,
    "write_post":       Domain.writing,
    "proofread":        Domain.writing,

    # Contacts (new — Phase 3)
    "add_contact":      Domain.contacts,
    "find_contact":     Domain.contacts,

    # General
    "general_chat":     Domain.general,
    "onboarding":       Domain.onboarding,
}
```

#### 6.1.2 Domain router wrapper

**File**: `src/core/domain_router.py` (NEW)

Wraps the existing `AgentRouter` with domain-level routing. The existing `router.py` delegates to this instead of directly to `AgentRouter`.

```python
"""Domain-level router — sits between master_router and AgentRouter."""

from src.core.domains import Domain, INTENT_DOMAIN_MAP
from src.agents.base import AgentRouter


class DomainRouter:
    """Routes intents through domain → agent → skill pipeline.

    Phase 1: thin wrapper around AgentRouter.
    Phase 2+: complex domains get LangGraph orchestrators.
    """

    def __init__(self, agent_router: AgentRouter):
        self._agent_router = agent_router
        self._orchestrators: dict[Domain, object] = {}

    def register_orchestrator(self, domain: Domain, orchestrator: object) -> None:
        self._orchestrators[domain] = orchestrator

    def get_domain(self, intent: str) -> Domain:
        return INTENT_DOMAIN_MAP.get(intent, Domain.general)

    async def route(self, intent, message, context, intent_data):
        domain = self.get_domain(intent)
        orchestrator = self._orchestrators.get(domain)

        if orchestrator:
            return await orchestrator.invoke(intent, message, context, intent_data)

        # Fallback: delegate to existing AgentRouter
        return await self._agent_router.route(intent, message, context, intent_data)
```

#### 6.1.3 Update `router.py` to use `DomainRouter`

**File**: `src/core/router.py`

Minimal change — replace `get_agent_router()` usage with `DomainRouter`:

```python
# BEFORE (line 52-57):
def get_agent_router() -> AgentRouter:
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter(AGENTS, get_registry())
    return _agent_router

# AFTER:
_domain_router: DomainRouter | None = None

def get_domain_router() -> DomainRouter:
    global _domain_router
    if _domain_router is None:
        agent_router = AgentRouter(AGENTS, get_registry())
        _domain_router = DomainRouter(agent_router)
    return _domain_router
```

All call sites in `router.py` that use `get_agent_router().route(...)` change to `get_domain_router().route(...)`. Behavior is identical in Phase 1 — `DomainRouter` passes everything through to `AgentRouter`.

---

### 6.2 Two-stage intent detection

#### 6.2.1 Design

Current: single prompt with 22 intents → Gemini Flash classifies.
Target: when intent count > 25, use two stages.

**Stage 1 — Domain Classification:**

```
Classify the user's message into one domain:
- finance (expenses, income, receipts, budgets, reports)
- email (inbox, send, reply, draft, follow-up)
- calendar (events, schedule, meetings, free slots)
- tasks (to-do, reminders, deadlines)
- research (search, compare, analyze)
- writing (draft, translate, proofread)
- contacts (people, CRM, follow-ups)
- general (life tracking, chat, mood, food, drinks)
- onboarding (setup, connect accounts)
```

Model: Gemini 3 Flash (`gemini-3-flash-preview`) — fast, cheap.

**Stage 2 — Intent within Domain:**

Each domain has its own focused prompt with 4-14 intents. Same model.

**Implementation:**

```python
# src/core/intent.py — add:

DOMAIN_CLASSIFICATION_PROMPT = """..."""  # Stage 1

DOMAIN_INTENT_PROMPTS: dict[str, str] = {
    "finance": """...""",   # 14 intents
    "email": """...""",     # 5 intents
    "calendar": """...""",  # 5 intents
    "tasks": """...""",     # 4 intents
    "research": """...""",  # 3 intents
    "writing": """...""",   # 4 intents
    "contacts": """...""",  # 2 intents
    "general": """...""",   # 9 intents (life + chat)
    "onboarding": """...""" # 1 intent
}


async def detect_intent_v2(message, context) -> IntentDetectionResult:
    """Two-stage intent detection for >25 intents."""

    # Stage 1: classify domain
    domain = await _classify_domain(message, context)

    # Stage 2: classify intent within domain
    result = await _classify_intent(message, context, domain)
    result.data.domain = domain

    return result
```

**Activation:** `detect_intent_v2()` is used when total registered intents > 25. Until then, the existing single-stage `detect_intent()` remains active. This is controlled by a simple check in `router.py`.

#### 6.2.2 Expand `IntentDetectionResult`

**File**: `src/core/schemas/intent.py`

```python
# ADD to IntentData:
    domain: str | None = None  # finance, email, calendar, tasks, etc.

    # Email fields (Phase 2)
    email_to: str | None = None
    email_subject: str | None = None
    email_body_hint: str | None = None

    # Calendar fields (Phase 2)
    event_title: str | None = None
    event_datetime: str | None = None
    event_duration_minutes: int | None = None
    event_attendees: list[str] | None = None

    # Task fields (Phase 3)
    task_title: str | None = None
    task_deadline: str | None = None
    task_priority: str | None = None

    # Research fields (Phase 3)
    search_topic: str | None = None

    # Writing fields (Phase 3)
    writing_topic: str | None = None
    target_language: str | None = None
    target_platform: str | None = None

    # Contact fields (Phase 3)
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
```

---

### 6.3 New database models

#### 6.3.1 New enums

**File**: `src/core/models/enums.py` — add:

```python
class TaskStatus(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"

class TaskPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"

class ContactRole(StrEnum):
    client = "client"
    vendor = "vendor"
    partner = "partner"
    friend = "friend"
    family = "family"
    doctor = "doctor"
    other = "other"

class MonitorType(StrEnum):
    price = "price"
    news = "news"
    competitor = "competitor"
    exchange_rate = "exchange_rate"

class SubscriptionStatus(StrEnum):
    active = "active"
    past_due = "past_due"
    cancelled = "cancelled"
    trial = "trial"

class ChannelType(StrEnum):
    telegram = "telegram"
    whatsapp = "whatsapp"
    slack = "slack"
    sms = "sms"
```

#### 6.3.2 New model files

Each file follows the existing pattern from `src/core/models/base.py` (TimestampMixin, UUID PK, family_id FK).

| New File | Table | Key Fields |
|----------|-------|------------|
| `src/core/models/contact.py` | `contacts` | name, phone, email, role, company, tags[], last_contact_at, next_followup_at |
| `src/core/models/task.py` | `tasks` | title, status, priority, due_at, reminder_at, assigned_to (FK contacts), domain, source_message_id |
| `src/core/models/email_cache.py` | `email_cache` | gmail_id, thread_id, from_email, subject, snippet, is_read, is_important, followup_needed |
| `src/core/models/calendar_cache.py` | `calendar_cache` | google_event_id, title, start_at, end_at, attendees (JSONB), prep_notes |
| `src/core/models/monitor.py` | `monitors` | type, name, config (JSONB), check_interval_minutes, last_value (JSONB), is_active |
| `src/core/models/user_profile.py` | `user_profiles` | display_name, timezone, preferred_language (default "en"), occupation, tone_preference, response_length, active_hours_start/end, learned_patterns (JSONB) |
| `src/core/models/usage_log.py` | `usage_logs` | domain, skill, model, tokens_input, tokens_output, cost_usd, duration_ms, success |
| `src/core/models/subscription.py` | `subscriptions` | stripe_customer_id, stripe_subscription_id, plan, status, trial_ends_at |

#### 6.3.3 Alembic migration

**File**: `alembic/versions/005_multi_domain_tables.py`

Creates all 8 new tables + RLS policies for each. Uses raw SQL pattern from existing `004_life_events.py` (no `sa.Enum(create_type=False)` — use `CREATE TYPE IF NOT EXISTS` instead).

#### 6.3.4 Update `src/core/models/__init__.py`

Import all new models so Alembic autogenerate picks them up.

---

### 6.4 Extend `SessionContext`

**File**: `src/core/context.py`

```python
# ADD fields to SessionContext:
    channel: str = "telegram"                  # telegram | whatsapp | slack | sms
    channel_user_id: str | None = None         # original platform user ID
    timezone: str = "America/New_York"         # user timezone
    active_domain: str | None = None           # current conversation domain
    user_profile: dict[str, Any] | None = None # learned preferences
```

---

### 6.5 Extend gateway types

**File**: `src/gateway/types.py`

```python
# ADD fields to IncomingMessage:
    channel: str = "telegram"           # source channel
    channel_user_id: str | None = None  # platform-specific user ID
    language: str | None = None         # detected language
    reply_to: str | None = None         # reply to another message
    group_id: str | None = None         # group chat ID

# ADD to MessageType enum:
    location = "location"

# ADD fields to OutgoingMessage:
    channel: str = "telegram"
    requires_approval: bool = False     # user must confirm before side-effect
    approval_action: str | None = None  # what action is pending approval
    approval_data: dict | None = None   # data for the pending action
```

---

### 6.6 Gateway abstraction

**File**: `src/gateway/base.py` (NEW)

```python
"""Base gateway protocol for multi-channel support."""

from typing import Protocol

class MessageGateway(Protocol):
    """All channel gateways implement this protocol."""

    channel_type: str

    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None: ...
    async def send_document(self, chat_id: str, document: bytes, filename: str) -> None: ...
    async def send_photo(self, chat_id: str, photo: bytes | str) -> None: ...
    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None: ...
```

**File**: `src/gateway/telegram.py` — refactor to implement `MessageGateway` protocol.

**File**: `src/gateway/factory.py` (NEW)

```python
"""Gateway factory — returns the right gateway for a channel type."""

def get_gateway(channel: str) -> MessageGateway:
    match channel:
        case "telegram":
            return TelegramGateway()
        case "whatsapp":
            return WhatsAppGateway()   # Phase 4
        case "slack":
            return SlackGateway()      # Phase 4
        case "sms":
            return SMSGateway()        # Phase 4
        case _:
            return TelegramGateway()   # default fallback
```

---

### 6.7 Phase 1 — file summary

| Action | File | Type |
|--------|------|------|
| NEW | `src/core/domains.py` | Domain enum + intent→domain map |
| NEW | `src/core/domain_router.py` | Domain routing wrapper |
| EDIT | `src/core/router.py` | Use `DomainRouter` instead of `AgentRouter` directly |
| EDIT | `src/core/intent.py` | Add 2-stage detection (activate later) |
| EDIT | `src/core/schemas/intent.py` | Add `domain` + future intent fields |
| EDIT | `src/core/context.py` | Add channel, timezone, active_domain fields |
| NEW | `src/gateway/base.py` | MessageGateway protocol |
| NEW | `src/gateway/factory.py` | Gateway factory |
| EDIT | `src/gateway/types.py` | Add channel, language, reply_to, approval fields |
| EDIT | `src/gateway/telegram.py` | Implement MessageGateway protocol |
| EDIT | `src/core/models/enums.py` | Add TaskStatus, ContactRole, MonitorType, etc. |
| NEW | `src/core/models/contact.py` | Contact model |
| NEW | `src/core/models/task.py` | Task model |
| NEW | `src/core/models/email_cache.py` | Email cache model |
| NEW | `src/core/models/calendar_cache.py` | Calendar cache model |
| NEW | `src/core/models/monitor.py` | Monitor model |
| NEW | `src/core/models/user_profile.py` | User profile model |
| NEW | `src/core/models/usage_log.py` | Usage log model |
| NEW | `src/core/models/subscription.py` | Subscription model |
| NEW | `alembic/versions/005_multi_domain_tables.py` | Migration |
| EDIT | `src/core/models/__init__.py` | Import new models |
| NEW | `tests/test_core/test_domains.py` | Domain mapping tests |
| NEW | `tests/test_core/test_domain_router.py` | Domain router tests |
| NEW | `tests/test_gateway/test_factory.py` | Gateway factory tests |

**Total Phase 1**: ~12 new files, ~9 edited files

---

## 7. PHASE 2: EMAIL + CALENDAR (Weeks 3-4)

### 7.1 Google Workspace integration via `aiogoogle`

#### 7.1.1 New file: `src/tools/google_workspace.py`

```python
"""Google Workspace API client — Gmail, Calendar.

Uses `aiogoogle` for native async access to Google APIs.
Each user has their own OAuth tokens stored encrypted in `oauth_tokens` table.
"""

from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import UserCreds, ClientCreds


class GoogleWorkspaceClient:
    """Per-user Google API client. Instantiated with user's OAuth tokens."""

    def __init__(self, user_creds: UserCreds, client_creds: ClientCreds):
        self._user_creds = user_creds
        self._client_creds = client_creds

    # Gmail
    async def list_messages(self, query: str, max_results: int = 20) -> list[dict]: ...
    async def get_message(self, message_id: str) -> dict: ...
    async def get_thread(self, thread_id: str) -> list[dict]: ...
    async def send_message(self, to: str, subject: str, body: str) -> dict: ...
    async def create_draft(self, to: str, subject: str, body: str) -> dict: ...

    # Calendar
    async def list_events(self, time_min: datetime, time_max: datetime) -> list[dict]: ...
    async def create_event(self, title: str, start: datetime, end: datetime, **kwargs) -> dict: ...
    async def update_event(self, event_id: str, **updates) -> dict: ...
    async def delete_event(self, event_id: str) -> None: ...
    async def get_free_busy(self, time_min: datetime, time_max: datetime) -> list[dict]: ...
```

#### 7.1.2 New dependency

**File**: `pyproject.toml`

```toml
aiogoogle = ">=5.0.0"
cryptography = ">=42.0.0"  # for token encryption
langgraph = ">=0.3.0"      # graph-based orchestrators
```

#### 7.1.3 OAuth flow

**File**: `api/oauth.py` (NEW)

```
GET /oauth/google/start?state=TOKEN  → redirect to Google consent screen
GET /oauth/google/callback           → exchange code for tokens, encrypt, store in DB
```

**Scopes requested:**
- `https://www.googleapis.com/auth/gmail.modify` (read + send)
- `https://www.googleapis.com/auth/calendar` (read + write)

**File**: `src/core/models/oauth_token.py` (NEW)

```python
class OAuthToken(Base, TimestampMixin):
    id: UUID
    user_id: UUID (FK users.id)
    family_id: UUID (FK families.id)  # for RLS
    provider: str  # "google"
    access_token_encrypted: bytes
    refresh_token_encrypted: bytes
    expires_at: datetime
    scopes: list[str]  # JSONB
```

Token encryption uses `cryptography.fernet.Fernet` with a key from environment variable `OAUTH_ENCRYPTION_KEY`.

**Auto-refresh:** Before any API call, check `expires_at`. If < 5 min remaining, refresh via `aiogoogle` and update DB.

---

### 7.2 Email orchestrator

#### 7.2.1 New file: `src/orchestrators/email/graph.py`

```python
"""Email orchestrator — LangGraph StateGraph.

Nodes: planner → reader → writer → reviewer → sender
Handles: read_inbox, send_email, draft_reply, follow_up_email, summarize_thread
"""

from langgraph.graph import StateGraph, END

email_graph = StateGraph(EmailState)
email_graph.add_node("planner", email_planner)
email_graph.add_node("reader", email_reader)
email_graph.add_node("writer", email_writer)
email_graph.add_node("reviewer", email_reviewer)
email_graph.add_node("sender", email_sender)

email_graph.add_edge("planner", "reader")
email_graph.add_conditional_edges("reader", route_email_action, {
    "reply": "writer",
    "forward": "sender",
    "summary": END,
    "followup": "writer",
})
email_graph.add_edge("writer", "reviewer")
email_graph.add_conditional_edges("reviewer", check_quality, {
    "approved": "sender",
    "revision": "writer",
    "ask_user": END,
})
email_graph.add_edge("sender", END)
```

#### 7.2.2 Email skills (5 new)

| New File | Intent | Model | Description |
|----------|--------|-------|-------------|
| `src/skills/read_inbox/handler.py` | `read_inbox` | claude-haiku-4-5 | List and summarize unread emails |
| `src/skills/send_email/handler.py` | `send_email` | claude-sonnet-4-6 | Compose and send email (requires_approval) |
| `src/skills/draft_reply/handler.py` | `draft_reply` | claude-sonnet-4-6 | Draft reply to email thread |
| `src/skills/follow_up_email/handler.py` | `follow_up_email` | claude-haiku-4-5 | Check for unanswered emails |
| `src/skills/summarize_thread/handler.py` | `summarize_thread` | claude-haiku-4-5 | Summarize email thread |

Each skill follows the existing BaseSkill pattern: `name`, `intents[]`, `model`, `execute()`, `get_system_prompt()`.

#### 7.2.3 Email agent config

**File**: `src/agents/config.py` — add:

```python
EMAIL_AGENT_PROMPT = """\
You are an email assistant. Help the user manage their Gmail inbox.
Read, summarize, draft, reply, and send emails.
Always show email content in a clean format.
For sending: ALWAYS ask for user confirmation before sending.
Respond in the user's preferred language (from context.language). Default: English."""

AgentConfig(
    name="email",
    system_prompt=EMAIL_AGENT_PROMPT,
    skills=["read_inbox", "send_email", "draft_reply", "follow_up_email", "summarize_thread"],
    default_model="claude-sonnet-4-6",
    context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
)
```

---

### 7.3 Calendar skills (via skill.execute(), no LangGraph)

Calendar operations are linear CRUD — no revision loops or branching needed. Each skill handles its own conflict checking inline.

#### 7.3.1 Calendar skills (5 new)

| New File | Intent | Model | Description |
|----------|--------|-------|-------------|
| `src/skills/list_events/handler.py` | `list_events` | claude-haiku-4-5 | Show today/week schedule |
| `src/skills/create_event/handler.py` | `create_event` | claude-haiku-4-5 | Create calendar event (requires_approval) |
| `src/skills/find_free_slots/handler.py` | `find_free_slots` | claude-haiku-4-5 | Find available time slots |
| `src/skills/reschedule_event/handler.py` | `reschedule_event` | claude-haiku-4-5 | Move event (requires_approval) |
| `src/skills/morning_brief/handler.py` | `morning_brief` | claude-haiku-4-5 | Morning schedule + tasks summary |

#### 7.3.2 Calendar agent config

**File**: `src/agents/config.py` — add:

```python
CALENDAR_AGENT_PROMPT = """\
You are a calendar assistant. Help the user manage their Google Calendar.
Show schedule, create events, find free slots, reschedule.
Always check for conflicts before creating events.
For creating/modifying: ask for confirmation.
Respond in the user's preferred language (from context.language). Default: English."""

AgentConfig(
    name="calendar",
    system_prompt=CALENDAR_AGENT_PROMPT,
    skills=["list_events", "create_event", "find_free_slots", "reschedule_event", "morning_brief"],
    default_model="claude-haiku-4-5",
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
```

---

### 7.4 Register email orchestrator with DomainRouter

**File**: `src/core/router.py`

Calendar goes through AgentRouter (skill.execute()). Only email gets a LangGraph orchestrator in Phase 2.

```python
def get_domain_router() -> DomainRouter:
    global _domain_router
    if _domain_router is None:
        agent_router = AgentRouter(AGENTS, get_registry())
        _domain_router = DomainRouter(agent_router)

        # Register LangGraph orchestrators (only for complex multi-step domains)
        from src.orchestrators.email.graph import EmailOrchestrator
        _domain_router.register_orchestrator(Domain.email, EmailOrchestrator())

    return _domain_router
```

---

### 7.5 Update intent detection

**File**: `src/core/intent.py`

Add 10 new intents. At this point we have 32 total intents, so 2-stage detection activates:

```
- read_inbox: check email, inbox summary ("check my email", "what's in my inbox")
- send_email: compose and send email ("email John about the meeting")
- draft_reply: reply to an email ("reply to that email")
- follow_up_email: check unanswered emails ("any emails I haven't replied to?")
- summarize_thread: summarize email thread ("summarize the thread with Sarah")
- list_events: show calendar/schedule ("what's on my calendar today?")
- create_event: create meeting/event ("schedule a meeting tomorrow at 3pm")
- find_free_slots: find available time ("when am I free this week?")
- reschedule_event: move an event ("move my 3pm to 4pm")
- morning_brief: morning summary ("morning brief", "what's my day look like?")
```

---

### 7.6 Update QUERY_CONTEXT_MAP

**File**: `src/core/memory/context.py`

```python
# Email intents
"read_inbox":       {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"send_email":       {"mem": "profile", "hist": 5, "sql": False, "sum": False},
"draft_reply":      {"mem": "profile", "hist": 5, "sql": False, "sum": False},
"follow_up_email":  {"mem": "profile", "hist": 0, "sql": False, "sum": False},
"summarize_thread": {"mem": False,     "hist": 0, "sql": False, "sum": False},

# Calendar intents
"list_events":      {"mem": "profile", "hist": 0, "sql": False, "sum": False},
"create_event":     {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"find_free_slots":  {"mem": False,     "hist": 0, "sql": False, "sum": False},
"reschedule_event": {"mem": False,     "hist": 3, "sql": False, "sum": False},
"morning_brief":    {"mem": "life",    "hist": 0, "sql": False, "sum": False},
```

---

### 7.7 Background sync tasks

**File**: `src/core/tasks/google_sync_tasks.py` (NEW)

```python
@broker.task(schedule=[{"cron": "*/10 * * * *"}])
async def sync_gmail_inbox():
    """Every 10 min: check for new emails for users with connected Gmail."""
    ...

@broker.task(schedule=[{"cron": "*/15 * * * *"}])
async def sync_calendar_events():
    """Every 15 min: sync upcoming calendar events."""
    ...
```

---

### 7.8 Phase 2 — file summary

| Action | File | Type |
|--------|------|------|
| NEW | `src/tools/google_workspace.py` | Google API client (aiogoogle) |
| NEW | `api/oauth.py` | OAuth endpoints |
| NEW | `src/core/models/oauth_token.py` | Token storage model |
| NEW | `alembic/versions/006_oauth_tokens.py` | Migration |
| NEW | `src/core/crypto.py` | Token encryption helpers |
| NEW | `src/orchestrators/__init__.py` | Package init |
| NEW | `src/orchestrators/base.py` | Base orchestrator protocol |
| NEW | `src/orchestrators/email/__init__.py` | Package init |
| NEW | `src/orchestrators/email/graph.py` | Email LangGraph |
| NEW | `src/orchestrators/email/nodes.py` | Graph nodes |
| NEW | `src/orchestrators/email/state.py` | EmailState TypedDict |
| NEW | `src/skills/read_inbox/` | 2 files (init + handler) |
| NEW | `src/skills/send_email/` | 2 files |
| NEW | `src/skills/draft_reply/` | 2 files |
| NEW | `src/skills/follow_up_email/` | 2 files |
| NEW | `src/skills/summarize_thread/` | 2 files |
| NEW | `src/skills/list_events/` | 2 files |
| NEW | `src/skills/create_event/` | 2 files |
| NEW | `src/skills/find_free_slots/` | 2 files |
| NEW | `src/skills/reschedule_event/` | 2 files |
| NEW | `src/skills/morning_brief/` | 2 files |
| NEW | `src/core/tasks/google_sync_tasks.py` | Background sync cron |
| EDIT | `src/skills/__init__.py` | Register 10 new skills |
| EDIT | `src/agents/config.py` | Add email + calendar agents (7 total) |
| EDIT | `src/core/intent.py` | Add 10 intents, activate 2-stage (32 total) |
| EDIT | `src/core/memory/context.py` | Add 10 QUERY_CONTEXT_MAP entries |
| EDIT | `src/core/router.py` | Register email/calendar orchestrators |
| EDIT | `pyproject.toml` | Add aiogoogle, cryptography, langgraph |
| NEW | `tests/test_skills/test_read_inbox.py` | etc. (10 test files) |
| NEW | `tests/test_orchestrators/__init__.py` | Package init |
| NEW | `tests/test_orchestrators/test_email_graph.py` | Orchestrator tests |
| NEW | `tests/test_tools/test_google_workspace.py` | API client tests |
| NEW | `tests/test_api/test_oauth.py` | OAuth flow tests |

**Total Phase 2**: ~35 new files, ~8 edited files, 10 new skills, 2 new agents

---

## 8. PHASE 3: TASKS + RESEARCH + WRITING + CRM (Weeks 5-6)

### 8.1 Task management

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/create_task/handler.py` | `create_task` | claude-haiku-4-5 |
| `src/skills/list_tasks/handler.py` | `list_tasks` | claude-haiku-4-5 |
| `src/skills/set_reminder/handler.py` | `set_reminder` | claude-haiku-4-5 |
| `src/skills/complete_task/handler.py` | `complete_task` | claude-haiku-4-5 |

Agent: `tasks` (claude-haiku-4-5)

Data: uses internal `tasks` table from Phase 1 migration (not Google Tasks API). Supports priorities, assignment, deadlines, recurring tasks.

---

### 8.2 Research

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/web_search_skill/handler.py` | `web_search` | claude-sonnet-4-6 |
| `src/skills/deep_research/handler.py` | `deep_research` | claude-sonnet-4-6 |
| `src/skills/compare_options/handler.py` | `compare_options` | claude-sonnet-4-6 |

Agent: `research` (claude-sonnet-4-6)

#### Web search tool

**File**: `src/tools/web_search.py` (NEW)

Uses Brave Search API directly via `httpx`:

```python
class BraveSearchClient:
    """Brave Search API wrapper."""

    async def search(self, query: str, count: int = 10) -> list[SearchResult]: ...
    async def fetch_page(self, url: str) -> str: ...  # HTML → markdown via trafilatura
```

**Dependency**: `httpx` (already present) + `trafilatura` (HTML→text) + `BRAVE_API_KEY` env var.

---

### 8.3 Writing (LangGraph orchestrator)

Writing uses LangGraph because drafting involves revision loops — the user may ask "make it more formal", "shorten it", "add a greeting" after the first draft.

#### 8.3.1 Writing orchestrator

**File**: `src/orchestrators/writing/graph.py`

```python
"""Writing orchestrator — LangGraph StateGraph.

Nodes: drafter → reviewer → reviser (loop) → finalizer
Handles: draft_message, translate_text, write_post, proofread
"""

writing_graph = StateGraph(WritingState)
writing_graph.add_node("drafter", write_draft)
writing_graph.add_node("reviewer", review_quality)
writing_graph.add_node("reviser", revise_draft)
writing_graph.add_node("finalizer", finalize_output)

writing_graph.add_edge("drafter", "reviewer")
writing_graph.add_conditional_edges("reviewer", check_quality, {
    "good": "finalizer",
    "needs_revision": "reviser",
})
writing_graph.add_edge("reviser", "reviewer")  # revision loop
writing_graph.add_edge("finalizer", END)
```

#### 8.3.2 Writing skills (4 new)

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/draft_message/handler.py` | `draft_message` | claude-sonnet-4-6 |
| `src/skills/translate_text/handler.py` | `translate_text` | claude-sonnet-4-6 |
| `src/skills/write_post/handler.py` | `write_post` | claude-sonnet-4-6 |
| `src/skills/proofread/handler.py` | `proofread` | claude-haiku-4-5 |

Agent: `writing` (claude-sonnet-4-6)

Uses `user_profiles.learned_patterns` for tone matching. Writing skills use the user's historical message style (stored in Mem0) to match their voice.

---

### 8.4 CRM / Contacts

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/add_contact/handler.py` | `add_contact` | claude-haiku-4-5 |
| `src/skills/find_contact/handler.py` | `find_contact` | claude-haiku-4-5 |

Agent: `contacts` (claude-haiku-4-5)

Data: uses `contacts` table from Phase 1 migration. Learns contact details from conversations (e.g., "call Mike at 555-1234" → adds/updates Mike's phone).

---

### 8.5 Update intent detection

**File**: `src/core/intent.py`

Add 13 new intents (45 total). All use 2-stage detection.

```
- create_task: create a to-do item ("add task: call dentist")
- list_tasks: show tasks ("what's on my list?")
- set_reminder: set a reminder ("remind me to call Mike at 3pm")
- complete_task: mark task done ("done with dentist call")
- web_search: quick search ("search for best plumber in Queens")
- deep_research: in-depth research ("research electric van options for my fleet")
- compare_options: compare alternatives ("compare QuickBooks vs Wave")
- draft_message: write a message ("draft a text to Mike about tomorrow's schedule")
- translate_text: translate text ("translate this to Spanish")
- write_post: write content ("write a Google review response")
- proofread: check text ("proofread this email")
- add_contact: add a person ("save Mike's number: 555-1234")
- find_contact: find a person ("what's Mike's number?")
```

---

### 8.6 Update QUERY_CONTEXT_MAP

**File**: `src/core/memory/context.py`

```python
# Task intents
"create_task":      {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"list_tasks":       {"mem": False,     "hist": 0, "sql": False, "sum": False},
"set_reminder":     {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"complete_task":    {"mem": False,     "hist": 3, "sql": False, "sum": False},

# Research intents
"web_search":       {"mem": False,     "hist": 3, "sql": False, "sum": False},
"deep_research":    {"mem": "profile", "hist": 5, "sql": False, "sum": True},
"compare_options":  {"mem": "profile", "hist": 5, "sql": False, "sum": True},

# Writing intents
"draft_message":    {"mem": "profile", "hist": 5, "sql": False, "sum": False},
"translate_text":   {"mem": False,     "hist": 3, "sql": False, "sum": False},
"write_post":       {"mem": "profile", "hist": 5, "sql": False, "sum": False},
"proofread":        {"mem": False,     "hist": 3, "sql": False, "sum": False},

# Contact intents
"add_contact":      {"mem": "profile", "hist": 3, "sql": False, "sum": False},
"find_contact":     {"mem": False,     "hist": 3, "sql": False, "sum": False},
```

---

### 8.7 Phase 3 — file summary

| Action | Count |
|--------|-------|
| LangGraph orchestrators | 2 (research, writing) |
| Simple orchestrators (AgentRouter) | 2 (tasks, contacts) |
| New skills | 13 |
| New agents | 4 |
| New tool files | 1 (`src/tools/web_search.py`) |
| New test files | ~17 |
| Edited files | ~8 (intent.py, config.py, context.py, registry, router, etc.) |

**Running totals after Phase 3**: 45 skills, 11 agents, 3 LangGraph orchestrators (email, research, writing)

---

## 9. PHASE 3.5: PLATFORM ARCHITECTURE (Weeks 7-8)

> **PRD:** `docs/prds/platform-architecture.md` | **Star Rating:** 5→7★ | **RICE:** 52.8
> **Inspired by:** Claude Cowork plugin architecture, Agent Teams orchestration patterns

### 9.1 YAML Prompt System

Externalize all system prompts into YAML files alongside skill handlers. Enables prompt iteration without code deployment.

#### 9.1.1 Prompt loader

**File:** `src/skills/prompt_loader.py` (NEW)

```python
"""YAML prompt loader with startup validation and caching."""

from pathlib import Path
import yaml

_cache: dict[Path, dict] = {}


def load_prompt(skill_dir: Path) -> dict:
    """Load prompts.yaml for a skill. Returns empty dict if not found."""
    if skill_dir not in _cache:
        yaml_path = skill_dir / "prompts.yaml"
        if yaml_path.exists():
            _cache[skill_dir] = yaml.safe_load(yaml_path.read_text())
        else:
            _cache[skill_dir] = {}
    return _cache[skill_dir]


def validate_all_prompts(skills_dir: Path) -> list[str]:
    """Validate all prompts.yaml files at startup. Returns list of errors."""
    errors = []
    for yaml_path in skills_dir.rglob("prompts.yaml"):
        try:
            data = yaml.safe_load(yaml_path.read_text())
            if "system_prompt" not in data:
                errors.append(f"{yaml_path}: missing 'system_prompt' key")
        except yaml.YAMLError as e:
            errors.append(f"{yaml_path}: {e}")
    return errors
```

#### 9.1.2 `prompts.yaml` schema

```yaml
name: list_events                     # skill name (must match handler.name)
description: Shows calendar events    # for auto-discovery (future)
model: claude-haiku-4-5              # default model override
intents:
  - list_events

system_prompt: |
  You are a calendar assistant for {user_name}.
  Language: {language}.
  Group events by day. Bullet points with time + title.
  Show free gaps between events.
  If no events: "Your calendar is clear! Want to schedule something?"
  Max 10 items. Use Telegram HTML (<b>, <i>, <code>).

variants:                             # for A/B testing (P2)
  empty_calendar: "Your calendar is clear for {period}."
  busy_day: "Packed day — {event_count} events from {first_time} to {last_time}."
```

#### 9.1.3 Migration of skill handlers

Each skill's `get_system_prompt()` changes from hardcoded string to:

```python
def get_system_prompt(self, context: SessionContext) -> str:
    prompts = load_prompt(Path(__file__).parent)
    if prompts and "system_prompt" in prompts:
        return prompts["system_prompt"].format(
            user_name=context.user_name or "there",
            language=context.language or "en",
        )
    # Fallback: existing hardcoded prompt
    return self._default_system_prompt(context)
```

**Migration priority (10 key skills first):**
1. `add_expense` — most-used skill, biggest prompt iteration value
2. `list_events` — stub needs real prompt for Phase 4
3. `read_inbox` — stub needs real prompt for Phase 4
4. `morning_brief` — orchestrator rewrite (see 9.4)
5. `list_tasks` — data-driven, needs formatting prompt
6. `query_stats` — analytics prompt tuning
7. `web_search` — search quality depends on prompt
8. `draft_message` — tone matching depends on prompt
9. `general_chat` — most frequent fallback
10. `onboarding` — first impression, critical

Remaining 33 skills migrated gradually. Skills without `prompts.yaml` work unchanged.

---

### 9.2 Connector Registry

Unified abstraction for all external service connections. Skills never import API libraries directly.

#### 9.2.1 BaseConnector protocol

**File:** `src/core/connectors/base.py` (NEW)

```python
"""Base connector protocol for external service integrations."""

from typing import Any, Protocol


class BaseConnector(Protocol):
    name: str
    is_configured: bool  # env vars present?

    async def connect(self, user_id: str) -> str:
        """Initiate connection. Returns auth URL for OAuth or confirmation string."""
        ...

    async def disconnect(self, user_id: str) -> bool:
        """Revoke tokens and remove connection."""
        ...

    async def is_connected(self, user_id: str) -> bool:
        """Check if user has valid, non-expired connection."""
        ...

    async def get_client(self, user_id: str) -> Any:
        """Return ready-to-use API client with valid tokens. Auto-refreshes if needed."""
        ...

    async def refresh_if_needed(self, user_id: str) -> None:
        """Refresh tokens if expiring within 5 minutes."""
        ...
```

#### 9.2.2 ConnectorRegistry

**File:** `src/core/connectors/__init__.py` (NEW)

```python
class ConnectorRegistry:
    _connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> BaseConnector | None:
        return self._connectors.get(name)

    def list_configured(self) -> list[str]:
        return [n for n, c in self._connectors.items() if c.is_configured]

    async def list_connected(self, user_id: str) -> list[str]:
        return [n for n, c in self._connectors.items() if await c.is_connected(user_id)]
```

#### 9.2.3 Google connector (refactor existing OAuth)

**File:** `src/core/connectors/google.py` (NEW)

Wraps existing `src/core/crypto.py` encryption + `oauth_tokens` table + `aiogoogle` client creation into the `BaseConnector` protocol. Existing `api/oauth.py` endpoints call `google_connector.connect()` / `google_connector.handle_callback()`.

#### 9.2.4 Connector config

**File:** `src/core/connectors/config.yaml` (NEW)

```yaml
connectors:
  google:
    type: oauth2
    provider: google
    scopes:
      gmail: [gmail.readonly, gmail.send, gmail.modify]
      calendar: [calendar.events, calendar.readonly]
    token_encryption: true
  slack:
    type: oauth2
    provider: slack
    scopes: [channels:read, chat:write, users:read]
  stripe:
    type: api_key
    env_var: STRIPE_SECRET_KEY
  whatsapp:
    type: api_key
    env_var: WHATSAPP_API_TOKEN
  twilio:
    type: api_key
    env_var: TWILIO_AUTH_TOKEN
```

#### 9.2.5 Skill handler impact

Before (hardcoded):
```python
from aiogoogle import Aiogoogle
# ... manual token loading, refresh, client creation
```

After (connector registry):
```python
google = connector_registry.get("google")
if not await google.is_connected(context.user_id):
    return SkillResult(
        response_text="Connect your Gmail first.",
        buttons=[{"text": "Connect Gmail", "url": await google.connect(context.user_id)}],
    )
client = await google.get_client(context.user_id)
emails = await client.list_messages("is:unread", max_results=10)
```

---

### 9.3 Plugin Bundles for Business Profiles

Extend `config/profiles/*.yaml` into self-contained plugin directories with prompt overrides, custom categories, and configurable morning brief sections.

#### 9.3.1 Plugin directory structure

```
config/plugins/
├── household/               # default
│   └── plugin.yaml
├── plumber/
│   ├── plugin.yaml
│   └── prompts/
│       ├── add_expense.yaml     # override: "Materials" not "Shopping"
│       └── query_report.yaml    # override: job profitability report
├── restaurant/
│   ├── plugin.yaml
│   └── prompts/
│       ├── add_expense.yaml     # override: "Food Cost" not "Groceries"
│       └── query_report.yaml    # override: food cost percentage report
├── taxi/
│   ├── plugin.yaml
│   └── prompts/
│       └── add_expense.yaml     # override: "Gas", "Car Wash" categories
└── delivery/
    ├── plugin.yaml
    └── prompts/
        └── add_expense.yaml
```

#### 9.3.2 `plugin.yaml` schema

```yaml
name: plumber
display_name: "Plumbing & Trades"
description: "For plumbers, electricians, and trade businesses"
persona_match: "David"  # which test persona this serves

categories:
  - { name: "Materials", icon: "🔧", keywords: ["home depot", "ferguson", "pvc", "copper"] }
  - { name: "Vehicle", icon: "🚐", keywords: ["gas", "oil change", "tires", "car wash"] }
  - { name: "Subcontractor", icon: "👷", keywords: ["helper", "apprentice", "subcontract"] }
  - { name: "Tools", icon: "🛠️", keywords: ["milwaukee", "dewalt", "drill", "makita"] }
  - { name: "Office", icon: "📋", keywords: ["quickbooks", "insurance", "license"] }

metrics:
  - revenue_per_job
  - materials_percentage
  - outstanding_invoices

morning_brief_sections:
  - jobs_today          # calendar events tagged as jobs
  - money_summary       # yesterday's spending + invoiced
  - outstanding         # overdue invoices
  - email_highlights    # important emails

evening_recap_sections:
  - completed_jobs      # tasks marked done today
  - spending_total      # total spent today
  - invoices_sent       # invoices created today

disabled_skills: []     # all enabled by default
```

#### 9.3.3 Plugin loader

**File:** `src/core/plugin_loader.py` (NEW)

```python
class PluginLoader:
    """Loads and caches plugin bundles from config/plugins/."""

    def load(self, plugin_name: str) -> PluginConfig:
        """Load plugin.yaml. Falls back to 'household' if not found."""
        ...

    def get_prompt_override(self, plugin_name: str, skill_name: str) -> str | None:
        """Check if plugin has a prompt override for this skill."""
        ...

    def get_categories(self, plugin_name: str) -> list[dict]:
        """Return plugin-specific expense categories."""
        ...

    def get_morning_brief_sections(self, plugin_name: str) -> list[str]:
        """Return which sections to include in morning brief."""
        ...
```

#### 9.3.4 Integration with SessionContext

```python
# In context.py — at context creation:
plugin = plugin_loader.load(user.profile_type or "household")
context = SessionContext(
    ...
    categories=plugin.get_categories(),
    profile_type=user.profile_type,
)
```

#### 9.3.5 Prompt override chain

Priority (highest first):
1. Plugin-specific prompt (`config/plugins/{type}/prompts/{skill}.yaml`)
2. Skill-specific prompt (`src/skills/{skill}/prompts.yaml`)
3. Hardcoded prompt in handler (legacy fallback)

---

### 9.4 Multi-Agent Orchestrator

Rewrite `morning_brief` and add `evening_recap` as orchestrator skills that collect data from multiple domains in parallel.

#### 9.4.1 Morning Brief rewrite

**File:** `src/skills/morning_brief/handler.py` (REWRITE)

```python
class MorningBriefSkill:
    name = "morning_brief"
    intents = ["morning_brief"]
    model = "claude-sonnet-4-6"  # upgraded: synthesis needs stronger model

    async def execute(self, message, context, intent_data) -> SkillResult:
        plugin = plugin_loader.load(context.profile_type or "household")
        sections = plugin.get_morning_brief_sections()

        # Parallel data collection with per-collector 3s timeout
        collectors = {
            "jobs_today": self._collect_events(context),
            "tasks": self._collect_tasks(context),
            "money_summary": self._collect_finance(context),
            "email_highlights": self._collect_emails(context),
            "outstanding": self._collect_invoices(context),
        }

        active = {k: v for k, v in collectors.items() if k in sections}
        results = await asyncio.gather(
            *(asyncio.wait_for(coro, timeout=3.0) for coro in active.values()),
            return_exceptions=True,
        )

        data = {}
        for key, result in zip(active.keys(), results):
            if isinstance(result, Exception):
                data[key] = f"({key} unavailable)"
            else:
                data[key] = result

        brief = await self._synthesize(data, context)
        return SkillResult(response_text=brief)
```

**Data collectors:**
- `_collect_events` → uses `connector_registry.get("google")` → Calendar API
- `_collect_tasks` → uses `get_open_tasks()` from existing list_tasks skill
- `_collect_finance` → direct SQL query for yesterday's transactions
- `_collect_emails` → uses `connector_registry.get("google")` → Gmail API
- `_collect_invoices` → SQL query for overdue recurring payments

**Graceful degradation:** If calendar not connected → skip calendar section. If Gmail not connected → skip email section. Brief still generates from available data.

#### 9.4.2 Evening Recap (NEW)

**File:** `src/skills/evening_recap/handler.py` (NEW)

Same orchestrator pattern. Sections: tasks completed today, total spending, events attended, mood (if tracked). Tone: wrap-up, not action items.

**Intent:** `evening_recap` — added to intent detection prompt.
**Agent:** `life` agent (context_config: `{"mem": "life", "hist": 0, "sql": False, "sum": False}`)

#### 9.4.3 QUERY_CONTEXT_MAP updates

```python
"morning_brief":  {"mem": "profile", "hist": 0, "sql": False, "sum": False},  # orchestrator loads its own data
"evening_recap":  {"mem": "profile", "hist": 0, "sql": False, "sum": False},  # same pattern
```

---

### 9.5 Progressive Context Disclosure

Dynamically reduce context loading for simple queries using regex heuristics.

#### 9.5.1 Complexity heuristic

**File:** `src/core/memory/context.py` — add function:

```python
import re

SIMPLE_PATTERNS = [
    r"^\d+[\s.,]?\s?\w{1,20}$",            # "100 кофе", "50.5 uber"
    r"^(да|нет|ок|ok|спасибо|thanks|thx)\b", # confirmations
    r"^(привет|hello|hi|hey)\b",            # greetings
    r"^(готово|done|сделано)\b",             # completions
    r"^\+?\d[\d\s\-()]{5,15}$",             # phone numbers
]

COMPLEX_SIGNALS = [
    "сравни", "compare", "тренд", "trend", "обычно", "usually",
    "прошлый", "last", "бюджет", "budget", "итого", "total",
    "за месяц", "за неделю", "this month", "this week",
    "как обычно", "as usual", "всего", "average", "средн",
]

# Intents that always need full context
ALWAYS_HEAVY = {"query_stats", "complex_query", "query_report", "deep_research"}


def _needs_heavy_context(message: str, intent: str) -> bool:
    if intent in ALWAYS_HEAVY:
        return True
    text = message.strip().lower()
    if any(re.match(p, text, re.I) for p in SIMPLE_PATTERNS):
        return False
    if any(s in text for s in COMPLEX_SIGNALS):
        return True
    return True  # conservative default: load everything
```

#### 9.5.2 Integration into `assemble_context()`

```python
async def assemble_context(user_id, family_id, current_message, intent, ...):
    config = QUERY_CONTEXT_MAP.get(intent, DEFAULT_CONFIG).copy()

    if not _needs_heavy_context(current_message, intent):
        config["mem"] = False
        config["sql"] = False
        config["sum"] = False
        config["hist"] = min(config.get("hist", 0), 1)

    # rest unchanged — load layers per config
    ...
```

#### 9.5.3 Token savings tracking

Add `context_tokens_saved` field to `usage_logs` table:

```python
# In assemble_context — after assembly:
original = estimate_tokens(QUERY_CONTEXT_MAP[intent])
actual = token_usage["total"]
saved = max(0, original - actual)
```

**Expected savings:**

| Query type | Current tokens | After | Savings |
|-----------|---------------|-------|---------|
| "100р кофе" | ~3,000 | ~500 | 83% |
| "спасибо" | ~5,000 | ~200 | 96% |
| "готово" | ~3,000 | ~200 | 93% |
| "сколько за месяц?" | ~15,000 | ~15,000 | 0% (correct) |

---

### 9.6 Phase 3.5 — file summary

| Action | File | Type |
|--------|------|------|
| NEW | `src/skills/prompt_loader.py` | YAML prompt loader + validator |
| NEW | `src/skills/*/prompts.yaml` (10 files) | Prompt YAML for 10 key skills |
| NEW | `src/core/connectors/__init__.py` | ConnectorRegistry |
| NEW | `src/core/connectors/base.py` | BaseConnector protocol |
| NEW | `src/core/connectors/google.py` | Google OAuth connector |
| NEW | `src/core/connectors/config.yaml` | Connector config |
| NEW | `src/core/plugin_loader.py` | Plugin bundle loader |
| NEW | `config/plugins/household/plugin.yaml` | Default plugin |
| NEW | `config/plugins/plumber/plugin.yaml` | Plumber plugin (David) |
| NEW | `config/plugins/plumber/prompts/add_expense.yaml` | Plumber expense prompt |
| NEW | `config/plugins/restaurant/plugin.yaml` | Restaurant plugin |
| NEW | `config/plugins/restaurant/prompts/add_expense.yaml` | Restaurant expense prompt |
| NEW | `config/plugins/taxi/plugin.yaml` | Taxi plugin |
| NEW | `src/skills/evening_recap/__init__.py` + `handler.py` | Evening recap orchestrator |
| REWRITE | `src/skills/morning_brief/handler.py` | Orchestrator rewrite |
| EDIT | `src/core/memory/context.py` | Progressive disclosure heuristic |
| EDIT | `src/skills/__init__.py` | Register evening_recap (44 skills) |
| EDIT | `src/core/intent.py` | Add evening_recap intent |
| EDIT | `src/core/domains.py` | Map evening_recap to general domain |
| EDIT | `src/agents/config.py` | Add evening_recap to life agent |
| NEW | `tests/test_skills/test_prompt_loader.py` | Prompt loader tests |
| NEW | `tests/test_core/test_connectors.py` | Connector registry tests |
| NEW | `tests/test_core/test_plugin_loader.py` | Plugin loader tests |
| NEW | `tests/test_skills/test_evening_recap.py` | Evening recap tests |
| NEW | `tests/test_core/test_progressive_context.py` | Context heuristic tests |
| EDIT | `tests/test_skills/test_morning_brief.py` | Update for orchestrator |
| EDIT | `tests/test_skills/test_registry.py` | Update skill count |

**Total Phase 3.5**: ~30 new files, ~8 edited files, 1 new skill, 1 rewritten skill

---

## 10. PHASE 4: CHANNELS + BILLING (Weeks 9-10)

### 10.1 Channel architecture

Each channel gets a Python gateway that implements the `MessageGateway` protocol from Phase 1. No external sidecar process — all channels run inside the same FastAPI application.

```
User (WhatsApp/Slack/SMS)
    ↓
Webhook endpoint (api/main.py)
    ↓
Channel gateway (src/gateway/{channel}_gw.py)
    ↓ converts to IncomingMessage
Standard pipeline (router.py → intent → domain → skill)
    ↓ returns SkillResult
Channel gateway formats and sends response
```

---

### 10.2 Slack channel

**Library**: `slack-bolt` (official Slack Python SDK, async support, actively maintained by Slack team)

**File**: `src/gateway/slack_gw.py` (NEW)

```python
"""Slack gateway using slack-bolt async."""

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler


class SlackGateway:
    """Implements MessageGateway protocol for Slack."""

    def __init__(self):
        self.app = AsyncApp(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
        )
        self._register_handlers()

    def _register_handlers(self):
        @self.app.message("")
        async def handle_message(message, say):
            incoming = self._to_incoming_message(message)
            result = await process_message(incoming)
            await say(self._format_slack_response(result))

    def _to_incoming_message(self, slack_msg: dict) -> IncomingMessage:
        return IncomingMessage(
            id=slack_msg["ts"],
            user_id=slack_msg["user"],
            chat_id=slack_msg["channel"],
            type=MessageType.text,
            text=slack_msg.get("text", ""),
            channel="slack",
            channel_user_id=slack_msg["user"],
        )

    def _format_slack_response(self, result: SkillResult) -> dict:
        """Convert SkillResult to Slack Block Kit format."""
        ...
```

**File**: `api/main.py` — add Slack endpoint:

```python
from src.gateway.slack_gw import slack_gateway

@app.post("/webhook/slack/events")
async def slack_events(request: Request):
    return await slack_gateway.handler.handle(request)
```

**Setup**: Slack App created via api.slack.com, with Events API (message.im, message.channels) and Bot Token Scopes (chat:write, users:read).

**Dependency**: `pyproject.toml` — add `slack-bolt>=1.20.0`

---

### 10.3 WhatsApp channel

**API**: WhatsApp Business Cloud API (Meta-hosted, no phone server needed)

**File**: `src/gateway/whatsapp_gw.py` (NEW)

```python
"""WhatsApp gateway using Business Cloud API via httpx."""

import httpx


class WhatsAppGateway:
    """Implements MessageGateway protocol for WhatsApp."""

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        )

    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None:
        await self._client.post(
            f"/{settings.whatsapp_phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": chat_id,
                "type": "text",
                "text": {"body": message.response_text},
            },
        )

    def parse_webhook(self, payload: dict) -> IncomingMessage | None:
        """Parse WhatsApp webhook payload into IncomingMessage."""
        ...
```

**File**: `api/main.py` — add WhatsApp endpoint:

```python
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    incoming = whatsapp_gateway.parse_webhook(payload)
    if incoming:
        result = await process_message(incoming)
        await whatsapp_gateway.send_message(incoming.chat_id, result)
    return {"status": "ok"}

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification challenge."""
    ...
```

**Setup**: Meta Business Account → WhatsApp Business API → webhook registration.

---

### 10.4 SMS channel

**Library**: `twilio` (Python SDK)

**File**: `src/gateway/sms_gw.py` (NEW)

```python
"""SMS gateway using Twilio."""

from twilio.rest import Client as TwilioClient


class SMSGateway:
    """Implements MessageGateway protocol for SMS."""

    def __init__(self):
        self._client = TwilioClient(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )

    async def send_message(self, chat_id: str, message: OutgoingMessage) -> None:
        self._client.messages.create(
            body=message.response_text[:1600],  # SMS limit
            from_=settings.twilio_phone_number,
            to=chat_id,
        )

    def parse_webhook(self, form_data: dict) -> IncomingMessage:
        return IncomingMessage(
            id=form_data["MessageSid"],
            user_id=form_data["From"],
            chat_id=form_data["From"],
            type=MessageType.text,
            text=form_data.get("Body", ""),
            channel="sms",
            channel_user_id=form_data["From"],
        )
```

**File**: `api/main.py` — add SMS endpoint:

```python
@app.post("/webhook/sms")
async def sms_webhook(request: Request):
    form_data = await request.form()
    incoming = sms_gateway.parse_webhook(dict(form_data))
    result = await process_message(incoming)
    await sms_gateway.send_message(incoming.chat_id, result)
    return Response(content="<Response></Response>", media_type="text/xml")
```

**Dependency**: `pyproject.toml` — add `twilio>=9.0.0`

---

### 10.5 iMessage — DEFERRED

Apple does not provide a public iMessage API. Options like BlueBubbles require a dedicated macOS machine and are fragile. **Deferred indefinitely** until Apple opens the platform or a reliable third-party solution emerges.

---

### 10.6 Channel user mapping

**File**: `src/core/models/channel_link.py` (NEW)

```python
class ChannelLink(Base, TimestampMixin):
    """Maps external channel user IDs to our internal user."""
    id: UUID
    user_id: UUID (FK users.id)
    family_id: UUID (FK families.id)
    channel: str  # telegram, whatsapp, slack, sms
    channel_user_id: str  # platform-specific ID
    channel_chat_id: str | None  # channel, workspace, etc.
    is_primary: bool = False
    linked_at: datetime
```

**Migration**: `alembic/versions/007_channel_links.py`

The first time a user messages from a new channel, we attempt to match by phone number or email. If no match, we start an onboarding flow on that channel.

---

### 10.7 Stripe billing

#### 9.7.1 New files

| File | Purpose |
|------|---------|
| `src/billing/__init__.py` | Package |
| `src/billing/stripe_client.py` | Stripe API wrapper (checkout, subscription, portal, webhook) |
| `src/billing/usage_tracker.py` | Track LLM token usage per request → `usage_logs` table |
| `src/billing/subscription.py` | Subscription CRUD, status checks, grace period logic |

#### 9.7.2 Pricing

```
Plan:           AI Life Assistant
Price:          $49/month
Trial:          7 days free
Grace period:   3 days past due before suspension
Payment:        Stripe Checkout → Customer Portal for management
```

#### 9.7.3 Usage tracking middleware

**File**: `src/core/router.py` — add post-processing:

```python
# After skill execution, log usage:
await usage_tracker.log(
    user_id=context.user_id,
    domain=domain.value,
    skill=intent,
    model=result.metadata.get("model", "unknown"),
    tokens_input=result.metadata.get("tokens_in", 0),
    tokens_output=result.metadata.get("tokens_out", 0),
    duration_ms=elapsed_ms,
)
```

#### 9.7.4 Stripe webhook

**File**: `api/main.py` — add:

```python
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription events (created, updated, deleted, payment_failed)."""
    ...
```

#### 9.7.5 Subscription check middleware

Added to `router.py` — before processing any message, verify the user has an active subscription (or is in trial/grace period). If not, respond with a payment link.

**Dependency**: `pyproject.toml` — add `stripe>=10.0.0`

---

### 10.8 Phase 4 — file summary

> **Note:** Phase 4 channel gateways now use `ConnectorRegistry` from Phase 3.5 for external service connections. Slack, WhatsApp, and Twilio connectors are registered in `src/core/connectors/` alongside Google. Skills access all services through the same `BaseConnector` protocol.

| Action | File | Type |
|--------|------|------|
| NEW | `src/gateway/slack_gw.py` | Slack gateway (slack-bolt) |
| NEW | `src/gateway/whatsapp_gw.py` | WhatsApp gateway (Business Cloud API) |
| NEW | `src/gateway/sms_gw.py` | SMS gateway (Twilio) |
| NEW | `src/core/models/channel_link.py` | Channel user mapping model |
| NEW | `alembic/versions/007_channel_links.py` | Migration |
| NEW | `src/billing/__init__.py` | Package init |
| NEW | `src/billing/stripe_client.py` | Stripe API wrapper |
| NEW | `src/billing/usage_tracker.py` | Token usage logging |
| NEW | `src/billing/subscription.py` | Subscription management |
| EDIT | `api/main.py` | Add /webhook/slack, /webhook/whatsapp, /webhook/sms, /webhook/stripe |
| EDIT | `src/gateway/factory.py` | Wire up new gateways |
| EDIT | `src/core/router.py` | Add usage tracking + subscription check |
| EDIT | `pyproject.toml` | Add slack-bolt, twilio, stripe |
| EDIT | `src/core/settings.py` | Add Slack, WhatsApp, Twilio, Stripe config |
| NEW | `tests/test_gateway/test_slack_gw.py` | Slack gateway tests |
| NEW | `tests/test_gateway/test_whatsapp_gw.py` | WhatsApp gateway tests |
| NEW | `tests/test_gateway/test_sms_gw.py` | SMS gateway tests |
| NEW | `tests/test_billing/test_stripe_client.py` | Stripe tests |
| NEW | `tests/test_billing/test_usage_tracker.py` | Usage tracking tests |
| NEW | `tests/test_billing/test_subscription.py` | Subscription tests |

**Total Phase 4**: ~14 new files, ~6 edited files, 3 new channel gateways

---

## 11. PHASE 5: PROACTIVITY + BROWSER AUTOMATION + POLISH (Weeks 11-12)

> **Note:** Phase 5 proactivity engine now leverages Phase 3.5 infrastructure: morning_brief orchestrator is already built (Phase 3.5), plugin bundles define proactive sections per business type, and progressive context disclosure reduces cost of frequent proactive checks.

### 11.1 Proactivity engine

| New File | Purpose |
|----------|---------|
| `src/proactivity/__init__.py` | Package |
| `src/proactivity/engine.py` | Main engine: evaluates triggers, decides actions |
| `src/proactivity/triggers.py` | Trigger definitions (morning_brief, follow_up, price_alert, etc.) |
| `src/proactivity/evaluator.py` | Condition evaluation WITHOUT LLM (pure logic) |
| `src/proactivity/scheduler.py` | Cron-like scheduler (extends existing Taskiq setup) |

Key design: the engine checks conditions **without LLM** first. Only generates content if a trigger fires, saving LLM costs. Example triggers:

```python
TRIGGERS = [
    # Morning brief at user's preferred time
    TimeTrigger(name="morning_brief", hour=7, action="send_morning_brief"),
    # Follow-up emails unanswered > 24h
    DataTrigger(name="email_followup", check=has_unanswered_emails, action="nudge_followup"),
    # Task deadline approaching
    DataTrigger(name="task_deadline", check=has_upcoming_deadlines, action="deadline_warning"),
    # Budget threshold exceeded
    DataTrigger(name="budget_alert", check=budget_exceeded, action="budget_warning"),
]
```

#### 11.1.1 Taskiq integration

**File**: `src/core/tasks/proactivity_tasks.py` (NEW)

```python
@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def evaluate_proactive_triggers():
    """Every 5 min: check all active users for proactive triggers."""
    ...
```

---

### 11.2 Browser automation (Browser-Use + LangGraph)

**Library**: `browser-use` (77K GitHub stars, MIT license, Python, 89.1% WebVoyager benchmark)

Browser automation uses LangGraph because tasks are inherently multi-step with retry loops: plan → execute in browser → verify result → retry if failed → approval before side effects.

**File**: `src/orchestrators/browser/graph.py` (NEW)

```python
"""Browser orchestrator — LangGraph StateGraph.

Nodes: planner → executor → verifier → (retry loop) → approval
"""

browser_graph = StateGraph(BrowserState)
browser_graph.add_node("planner", plan_browser_task)
browser_graph.add_node("executor", execute_in_browser)
browser_graph.add_node("verifier", verify_result)
browser_graph.add_node("approval", request_user_approval)

browser_graph.add_edge("planner", "executor")
browser_graph.add_edge("executor", "verifier")
browser_graph.add_conditional_edges("verifier", check_success, {
    "success": "approval",
    "retry": "executor",
    "failed": END,
})
browser_graph.add_edge("approval", END)
```

**File**: `src/tools/browser.py` (NEW)

```python
"""AI browser automation using Browser-Use library."""

from browser_use import Agent as BrowserAgent
from langchain_anthropic import ChatAnthropic


class BrowserTool:
    """Executes browser tasks via Browser-Use + Claude Sonnet 4.6."""

    def __init__(self):
        self._llm = ChatAnthropic(model="claude-sonnet-4-6")

    async def execute_task(self, task: str, max_steps: int = 10) -> str:
        """Run a browser automation task and return the result."""
        agent = BrowserAgent(task=task, llm=self._llm)
        result = await agent.run(max_steps=max_steps)
        return result
```

**Production**: For production use, pair with Steel.dev for isolated Chrome containers:

```python
from browser_use import Browser, BrowserConfig

browser = Browser(config=BrowserConfig(
    cdp_url=f"wss://connect.steel.dev?apiKey={settings.steel_api_key}"
))
```

**Use cases** (Phase 5):
- Book restaurant reservations
- Fill out government forms
- Check price on a website
- Submit Google reviews

**Dependency**: `pyproject.toml` — add `browser-use>=0.2.0`, `langchain-anthropic>=0.3.0`

**Skills** (2 new):

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/web_action/handler.py` | `web_action` | claude-sonnet-4-6 |
| `src/skills/price_check/handler.py` | `price_check` | claude-haiku-4-5 |

---

### 11.3 Monitor skills

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/price_alert/handler.py` | `price_alert` | claude-haiku-4-5 |
| `src/skills/news_monitor/handler.py` | `news_monitor` | claude-haiku-4-5 |

Uses `monitors` table + `web_search` tool + Taskiq cron.

---

### 11.4 Action approval system

**File**: `src/core/approval.py` (NEW)

For actions that require user confirmation (send_email, create_event, web_action):

```python
class ApprovalManager:
    """Manages pending user approvals via inline keyboard buttons."""

    async def request_approval(self, user_id, action, data) -> SkillResult:
        """Returns SkillResult with confirmation buttons."""
        ...

    async def handle_approval(self, callback_data) -> SkillResult:
        """Executes the approved action."""
        ...

    async def handle_rejection(self, callback_data) -> SkillResult:
        """Cancels the pending action."""
        ...
```

---

### 11.5 User profile auto-learning

**File**: `src/core/tasks/profile_tasks.py` (NEW)

```python
@broker.task(schedule=[{"cron": "0 3 * * *"}])
async def update_user_profiles():
    """Daily: analyze last 50 messages per user, update learned_patterns."""
    ...
```

Learns: preferred language, response length, tone, active hours, common contacts, recurring patterns.

---

### 11.6 Onboarding expansion

**File**: `src/skills/onboarding/handler.py` — edit:

- Detect language from first message (English default, Spanish second priority)
- After first few interactions, offer to set preferred language: "Want me to always reply in [detected language]?"
- Store `preferred_language` in `user_profiles` table
- Support "change language to X" command anytime
- Ask about connected services (Gmail, Calendar) instead of just business type
- Guide through OAuth connection
- Proactive suggestions based on first few interactions

---

### 11.7 Phase 5 — file summary

| Action | Count |
|--------|-------|
| New proactivity files | 5 |
| New browser tool | 1 (`src/tools/browser.py`) |
| New skills | 4 (web_action, price_check, price_alert, news_monitor) |
| New approval system | 1 |
| New profile learning task | 1 |
| Edited onboarding | 1 |
| New test files | ~8 |

**Running totals after Phase 5**: 53 skills, 11 agents, 2 active LangGraph orchestrators

---

## 12. PHASE 6: BOOKING + CRM

### 12.1 Contacts + Bookings + Client Interactions

Phase 6 expanded the CRM foundation (Phase 3's `add_contact`/`find_contact`) into a full booking and client management system for service businesses.

#### 12.1.1 New skills (8 total in CRM/booking domain)

| Skill | Intent | Model | Description |
|-------|--------|-------|-------------|
| `add_contact` | `add_contact` | claude-haiku-4-5 | Save contact (name, phone, email, role) |
| `list_contacts` | `list_contacts` | claude-haiku-4-5 | Show all contacts with filters |
| `find_contact` | `find_contact` | claude-haiku-4-5 | Search contacts by name/role |
| `create_booking` | `create_booking` | claude-haiku-4-5 | Schedule appointment/job |
| `list_bookings` | `list_bookings` | claude-haiku-4-5 | Show upcoming bookings |
| `cancel_booking` | `cancel_booking` | claude-haiku-4-5 | Cancel a booking |
| `reschedule_booking` | `reschedule_booking` | claude-haiku-4-5 | Move booking to new time |
| `send_to_client` | `send_to_client` | claude-sonnet-4-6 | Draft and send message to client |

Agent: `booking` (claude-haiku-4-5)

#### 12.1.2 Database tables

**Migration:** `alembic/versions/007_bookings.py` (merge migration — `down_revision = ("006", "006b")`)

| Table | Key Fields |
|-------|------------|
| `bookings` | title, service_type, start_at, end_at, location, status (enum: scheduled/confirmed/completed/cancelled/no_show), contact_id FK, reminder_sent, confirmation_sent |
| `client_interactions` | contact_id FK, channel (enum: phone/telegram/whatsapp/sms/email), direction (enum: inbound/outbound), content, booking_id FK, call_duration_seconds |

Both tables have RLS policies for family_id isolation.

#### 12.1.3 Phase 6 — file summary

| Action | Count |
|--------|-------|
| New skills | 8 (add_contact, list_contacts, find_contact, create_booking, list_bookings, cancel_booking, reschedule_booking, send_to_client) |
| New agent | 1 (booking) |
| New DB tables | 2 (bookings, client_interactions) + 3 enums |
| Alembic migration | 1 (007_bookings.py — merge point) |
| New test files | ~8 |
| Edited files | ~4 (skills/__init__.py, agents/config.py, intent.py, context.py) |

**Running totals after Phase 6**: 61 skills, 11 agents, 2 active LangGraph orchestrators, 28 DB tables

---

## 13. FILE-BY-FILE CHANGE MAP

### Complete file listing across all phases

```
Legend:  [NEW] = new file  [EDIT] = modify existing  [FIX] = bugfix

═══════════════════════════════════════════════════════════════
PHASE 0: BUGFIXES
═══════════════════════════════════════════════════════════════
[FIX]  src/agents/config.py                        # query_report → analytics
[FIX]  src/core/memory/context.py                  # 4 missing + 1 dead + 1 duplicate

═══════════════════════════════════════════════════════════════
PHASE 1: CORE GENERALIZATION (Weeks 1-2)
═══════════════════════════════════════════════════════════════
[NEW]  src/core/domains.py                         # Domain enum + INTENT_DOMAIN_MAP
[NEW]  src/core/domain_router.py                   # DomainRouter wrapper
[NEW]  src/gateway/base.py                         # MessageGateway protocol
[NEW]  src/gateway/factory.py                      # Gateway factory
[EDIT] src/core/router.py                          # Use DomainRouter
[EDIT] src/core/intent.py                          # Add 2-stage detection (activate in Phase 2)
[EDIT] src/core/schemas/intent.py                  # Add domain + future fields
[EDIT] src/core/context.py                         # Add channel, timezone, profile
[EDIT] src/gateway/types.py                        # Add channel, language, approval
[EDIT] src/gateway/telegram.py                     # Implement MessageGateway protocol
[EDIT] src/core/models/enums.py                    # New enums
[NEW]  src/core/models/contact.py                  # Contact model
[NEW]  src/core/models/task.py                     # Task model
[NEW]  src/core/models/email_cache.py              # Email cache model
[NEW]  src/core/models/calendar_cache.py           # Calendar cache model
[NEW]  src/core/models/monitor.py                  # Monitor model
[NEW]  src/core/models/user_profile.py             # User profile model
[NEW]  src/core/models/usage_log.py                # Usage log model
[NEW]  src/core/models/subscription.py             # Subscription model
[EDIT] src/core/models/__init__.py                 # Import new models
[NEW]  alembic/versions/005_multi_domain_tables.py # Migration for 8 new tables + RLS
[NEW]  tests/test_core/test_domains.py             # Domain mapping tests
[NEW]  tests/test_core/test_domain_router.py       # Domain router tests
[NEW]  tests/test_gateway/test_factory.py          # Gateway factory tests

═══════════════════════════════════════════════════════════════
PHASE 2: EMAIL + CALENDAR (Weeks 3-4)
═══════════════════════════════════════════════════════════════
[NEW]  src/tools/google_workspace.py               # Google API client (aiogoogle)
[NEW]  src/core/crypto.py                          # Token encryption (Fernet)
[NEW]  api/oauth.py                                # Google OAuth endpoints
[NEW]  src/core/models/oauth_token.py              # OAuth token model
[NEW]  alembic/versions/006_oauth_tokens.py        # Migration
[NEW]  src/orchestrators/__init__.py               # Package init
[NEW]  src/orchestrators/base.py                   # Base orchestrator protocol
[NEW]  src/orchestrators/email/__init__.py         #
[NEW]  src/orchestrators/email/graph.py            # Email LangGraph StateGraph
[NEW]  src/orchestrators/email/nodes.py            # Planner, reader, writer, reviewer, sender
[NEW]  src/orchestrators/email/state.py            # EmailState TypedDict
[NEW]  src/skills/read_inbox/__init__.py + handler.py        # Read inbox skill
[NEW]  src/skills/send_email/__init__.py + handler.py        # Send email skill
[NEW]  src/skills/draft_reply/__init__.py + handler.py       # Draft reply skill
[NEW]  src/skills/follow_up_email/__init__.py + handler.py   # Follow-up skill
[NEW]  src/skills/summarize_thread/__init__.py + handler.py  # Summarize thread skill
[NEW]  src/skills/list_events/__init__.py + handler.py       # List events skill
[NEW]  src/skills/create_event/__init__.py + handler.py      # Create event skill
[NEW]  src/skills/find_free_slots/__init__.py + handler.py   # Find free slots skill
[NEW]  src/skills/reschedule_event/__init__.py + handler.py  # Reschedule event skill
[NEW]  src/skills/morning_brief/__init__.py + handler.py     # Morning brief skill
[NEW]  src/core/tasks/google_sync_tasks.py         # Background Gmail/Calendar sync
[EDIT] src/skills/__init__.py                      # Register 10 new skills (32 total)
[EDIT] src/agents/config.py                        # Add email + calendar agents (7 total)
[EDIT] src/core/intent.py                          # Add 10 intents, activate 2-stage
[EDIT] src/core/memory/context.py                  # Add 10 QUERY_CONTEXT_MAP entries
[EDIT] src/core/router.py                          # Register email/calendar orchestrators
[EDIT] pyproject.toml                              # Add aiogoogle, cryptography, langgraph
[NEW]  tests/test_skills/test_read_inbox.py        #
[NEW]  tests/test_skills/test_send_email.py        #
[NEW]  tests/test_skills/test_draft_reply.py       #
[NEW]  tests/test_skills/test_follow_up_email.py   #
[NEW]  tests/test_skills/test_summarize_thread.py  #
[NEW]  tests/test_skills/test_list_events.py       #
[NEW]  tests/test_skills/test_create_event.py      #
[NEW]  tests/test_skills/test_find_free_slots.py   #
[NEW]  tests/test_skills/test_reschedule_event.py  #
[NEW]  tests/test_skills/test_morning_brief.py     #
[NEW]  tests/test_orchestrators/__init__.py        #
[NEW]  tests/test_orchestrators/test_email_graph.py   #
[NEW]  tests/test_tools/test_google_workspace.py   #
[NEW]  tests/test_api/test_oauth.py                #

═══════════════════════════════════════════════════════════════
PHASE 3: TASKS + RESEARCH + WRITING + CRM (Weeks 5-6)
═══════════════════════════════════════════════════════════════
[NEW]  src/tools/web_search.py                     # Brave Search API client
[NEW]  src/orchestrators/research/__init__.py + graph.py + nodes.py + state.py  # Research LangGraph
[NEW]  src/orchestrators/writing/__init__.py + graph.py + nodes.py + state.py  # Writing LangGraph
[NEW]  src/skills/create_task/__init__.py + handler.py       #
[NEW]  src/skills/list_tasks/__init__.py + handler.py        #
[NEW]  src/skills/set_reminder/__init__.py + handler.py      #
[NEW]  src/skills/complete_task/__init__.py + handler.py     #
[NEW]  src/skills/web_search_skill/__init__.py + handler.py  #
[NEW]  src/skills/deep_research/__init__.py + handler.py     #
[NEW]  src/skills/compare_options/__init__.py + handler.py   #
[NEW]  src/skills/draft_message/__init__.py + handler.py     #
[NEW]  src/skills/translate_text/__init__.py + handler.py    #
[NEW]  src/skills/write_post/__init__.py + handler.py        #
[NEW]  src/skills/proofread/__init__.py + handler.py         #
[NEW]  src/skills/add_contact/__init__.py + handler.py       #
[NEW]  src/skills/find_contact/__init__.py + handler.py      #
[EDIT] src/skills/__init__.py                      # Register 13 new skills (45 total)
[EDIT] src/agents/config.py                        # Add 4 agents (11 total)
[EDIT] src/core/intent.py                          # Add 13 intents (45 total)
[EDIT] src/core/memory/context.py                  # Add 13 QUERY_CONTEXT_MAP entries
[EDIT] src/core/router.py                          # Register 4 orchestrators
[EDIT] src/core/domains.py                         # Verify all new intents mapped
[EDIT] pyproject.toml                              # Add trafilatura
[NEW]  tests/test_skills/ (13 new test files)      #
[NEW]  tests/test_orchestrators/ (4 new test files)#
[NEW]  tests/test_tools/test_web_search.py         #

═══════════════════════════════════════════════════════════════
PHASE 3.5: PLATFORM ARCHITECTURE (Weeks 7-8) 🆕
═══════════════════════════════════════════════════════════════
[NEW]  src/skills/prompt_loader.py                  # YAML prompt loader + validator
[NEW]  src/skills/add_expense/prompts.yaml          # Prompt YAML (10 key skills)
[NEW]  src/skills/list_events/prompts.yaml          #
[NEW]  src/skills/read_inbox/prompts.yaml           #
[NEW]  src/skills/morning_brief/prompts.yaml        #
[NEW]  src/skills/list_tasks/prompts.yaml           #
[NEW]  src/skills/query_stats/prompts.yaml          #
[NEW]  src/skills/web_search/prompts.yaml           #
[NEW]  src/skills/draft_message/prompts.yaml        #
[NEW]  src/skills/general_chat/prompts.yaml         #
[NEW]  src/skills/onboarding/prompts.yaml           #
[NEW]  src/core/connectors/__init__.py              # ConnectorRegistry
[NEW]  src/core/connectors/base.py                  # BaseConnector protocol
[NEW]  src/core/connectors/google.py                # Google OAuth connector
[NEW]  src/core/connectors/config.yaml              # Connector config
[NEW]  src/core/plugin_loader.py                    # Plugin bundle loader
[NEW]  config/plugins/household/plugin.yaml         # Default plugin
[NEW]  config/plugins/plumber/plugin.yaml           # Plumber plugin (David persona)
[NEW]  config/plugins/plumber/prompts/add_expense.yaml
[NEW]  config/plugins/restaurant/plugin.yaml        # Restaurant plugin
[NEW]  config/plugins/restaurant/prompts/add_expense.yaml
[NEW]  config/plugins/taxi/plugin.yaml              # Taxi plugin
[NEW]  src/skills/evening_recap/__init__.py         # Evening recap orchestrator
[NEW]  src/skills/evening_recap/handler.py          #
[NEW]  src/skills/evening_recap/prompts.yaml        #
[REWRITE] src/skills/morning_brief/handler.py       # Orchestrator rewrite
[EDIT] src/core/memory/context.py                   # Progressive disclosure heuristic
[EDIT] src/skills/__init__.py                       # Register evening_recap
[EDIT] src/core/intent.py                           # Add evening_recap intent
[EDIT] src/core/domains.py                          # Map evening_recap
[EDIT] src/agents/config.py                         # Add evening_recap to life agent
[NEW]  tests/test_skills/test_prompt_loader.py      #
[NEW]  tests/test_core/test_connectors.py           #
[NEW]  tests/test_core/test_plugin_loader.py        #
[NEW]  tests/test_skills/test_evening_recap.py      #
[NEW]  tests/test_core/test_progressive_context.py  #
[EDIT] tests/test_skills/test_morning_brief.py      # Update for orchestrator
[EDIT] tests/test_skills/test_registry.py           # Update skill count

═══════════════════════════════════════════════════════════════
PHASE 4: CHANNELS + BILLING (Weeks 9-10)
═══════════════════════════════════════════════════════════════
[NEW]  src/gateway/slack_gw.py                     # Slack gateway (slack-bolt)
[NEW]  src/gateway/whatsapp_gw.py                  # WhatsApp gateway (Business Cloud API)
[NEW]  src/gateway/sms_gw.py                       # SMS gateway (Twilio)
[NEW]  src/core/models/channel_link.py             # Channel user mapping model
[NEW]  alembic/versions/007_channel_links.py       # Migration
[NEW]  src/billing/__init__.py                     # Package
[NEW]  src/billing/stripe_client.py                # Stripe API wrapper
[NEW]  src/billing/usage_tracker.py                # Token usage logging
[NEW]  src/billing/subscription.py                 # Subscription management
[EDIT] api/main.py                                 # Add 4 webhook endpoints
[EDIT] src/gateway/factory.py                      # Wire up new gateways
[EDIT] src/core/router.py                          # Add usage tracking + subscription check
[EDIT] src/core/settings.py                        # Add Slack, WhatsApp, Twilio, Stripe config
[EDIT] pyproject.toml                              # Add slack-bolt, twilio, stripe
[NEW]  tests/test_gateway/test_slack_gw.py         #
[NEW]  tests/test_gateway/test_whatsapp_gw.py      #
[NEW]  tests/test_gateway/test_sms_gw.py           #
[NEW]  tests/test_billing/test_stripe_client.py    #
[NEW]  tests/test_billing/test_usage_tracker.py    #
[NEW]  tests/test_billing/test_subscription.py     #

═══════════════════════════════════════════════════════════════
PHASE 5: PROACTIVITY + BROWSER AUTOMATION + POLISH (Weeks 11-12)
═══════════════════════════════════════════════════════════════
[NEW]  src/proactivity/__init__.py                 #
[NEW]  src/proactivity/engine.py                   # Main proactivity engine
[NEW]  src/proactivity/triggers.py                 # Trigger definitions
[NEW]  src/proactivity/evaluator.py                # Condition evaluation (no LLM)
[NEW]  src/proactivity/scheduler.py                # Scheduler (Taskiq integration)
[NEW]  src/core/tasks/proactivity_tasks.py         # Cron tasks (every 5 min)
[NEW]  src/core/tasks/profile_tasks.py             # User profile auto-learning (daily)
[NEW]  src/core/approval.py                        # Action approval system
[NEW]  src/orchestrators/browser/__init__.py + graph.py + nodes.py + state.py  # Browser LangGraph
[NEW]  src/tools/browser.py                        # Browser-Use integration
[NEW]  src/skills/web_action/__init__.py + handler.py        # Web action skill
[NEW]  src/skills/price_check/__init__.py + handler.py       # Price check skill
[NEW]  src/skills/price_alert/__init__.py + handler.py       # Price alert skill
[NEW]  src/skills/news_monitor/__init__.py + handler.py      # News monitor skill
[EDIT] src/skills/__init__.py                      # Register 4 skills (49 total)
[EDIT] src/agents/config.py                        # Add monitor agent (12 total)
[EDIT] src/core/intent.py                          # Add 4 intents (49 total)
[EDIT] src/core/router.py                          # Integrate approval system
[EDIT] src/skills/onboarding/handler.py            # English + multi-domain onboarding
[EDIT] pyproject.toml                              # Add browser-use, langchain-anthropic
[NEW]  tests/test_proactivity/test_engine.py       #
[NEW]  tests/test_proactivity/test_triggers.py     #
[NEW]  tests/test_proactivity/test_evaluator.py    #
[NEW]  tests/test_tools/test_browser.py            #
[NEW]  tests/test_skills/test_web_action.py        #
[NEW]  tests/test_skills/test_price_check.py       #
[NEW]  tests/test_skills/test_price_alert.py       #
[NEW]  tests/test_skills/test_news_monitor.py      #

═══════════════════════════════════════════════════════════════
PHASE 6: BOOKING + CRM (Weeks 13-14)
═══════════════════════════════════════════════════════════════
[NEW]  src/skills/add_contact/__init__.py + handler.py        # Add contact
[NEW]  src/skills/list_contacts/__init__.py + handler.py      # List contacts
[NEW]  src/skills/find_contact/__init__.py + handler.py       # Search contacts
[NEW]  src/skills/create_booking/__init__.py + handler.py     # Create booking
[NEW]  src/skills/list_bookings/__init__.py + handler.py      # List bookings
[NEW]  src/skills/cancel_booking/__init__.py + handler.py     # Cancel booking
[NEW]  src/skills/reschedule_booking/__init__.py + handler.py # Reschedule booking
[NEW]  src/skills/send_to_client/__init__.py + handler.py     # Send to client
[NEW]  alembic/versions/006_channel_links.py                  # Channel links migration (006b)
[NEW]  alembic/versions/007_bookings.py                       # Bookings + client_interactions (merge point)
[EDIT] src/skills/__init__.py                      # Register 8 CRM/booking skills (61 total)
[EDIT] src/agents/config.py                        # Add booking agent (11 total)
[EDIT] src/core/intent.py                          # Add 8 booking/CRM intents
[EDIT] src/core/memory/context.py                  # Add QUERY_CONTEXT_MAP entries
[NEW]  tests/test_skills/test_add_contact.py       #
[NEW]  tests/test_skills/test_list_contacts.py     #
[NEW]  tests/test_skills/test_find_contact.py      #
[NEW]  tests/test_skills/test_create_booking.py    #
[NEW]  tests/test_skills/test_list_bookings.py     #
[NEW]  tests/test_skills/test_cancel_booking.py    #
[NEW]  tests/test_skills/test_reschedule_booking.py #
[NEW]  tests/test_skills/test_send_to_client.py    #

═══════════════════════════════════════════════════════════════
ADDITIONAL: Maps + YouTube dual-mode (Research domain)
═══════════════════════════════════════════════════════════════
[NEW]  src/skills/maps_search/__init__.py + handler.py        # Dual-mode: Gemini grounding + REST API
[NEW]  src/skills/youtube_search/__init__.py + handler.py     # Dual-mode + YouTube URL analysis
[NEW]  tests/test_skills/test_maps_search.py                  # 12 tests
[NEW]  tests/test_skills/test_youtube_search.py               # 20 tests
[EDIT] src/skills/__init__.py                                 # Register maps_search + youtube_search
[EDIT] src/core/intent.py                                     # Add maps_search, youtube_search intents
[EDIT] src/core/schemas/intent.py                             # Add maps_*, youtube_*, detail_mode fields
[EDIT] src/core/memory/context.py                             # Add QUERY_CONTEXT_MAP entries
```

---

## 14. RISK REGISTER

| # | Risk | Impact | Probability | Mitigation |
|---|------|--------|-------------|------------|
| 1 | Google OAuth rejection (app review) | High | Medium | Apply for verification early in Phase 2. Use restricted scopes. Have test accounts for development. |
| 2 | WhatsApp Business API approval delay | Medium | Medium | Start Meta Business verification in Phase 1. Use test phone numbers until approved. |
| 3 | LLM cost exceeds $8/user target | High | Low | Monitor via `usage_logs` table. Use Haiku 4.5 for 70% of calls. Cache common responses. Batch proactivity checks. |
| 4 | Two-stage intent detection latency | Medium | Low | Stage 1 adds ~80ms. Acceptable for text chat. Monitor via Langfuse. Fall back to single-stage if issues. |
| 5 | Browser-Use reliability in production | Medium | Medium | Use Steel.dev isolated containers. Set max_steps limit. Require user approval for all browser actions. Human-in-the-loop for critical tasks. |
| 6 | Stripe integration with multi-channel onboarding | Low | Low | Generate payment links that work across all channels. Use Stripe Customer Portal for management. |
| 7 | aiogoogle breaking changes | Low | Low | Pin version. aiogoogle has stable API. Google APIs themselves are versioned. |
| 8 | Token storage encryption key rotation | Medium | Low | Design key rotation from the start. Use key ID prefix on encrypted tokens. Support multiple active keys. |
| 9 | YAML parsing errors crash skill loading | High | Low | Validate all YAML at startup via `validate_all_prompts()`. Fall back to hardcoded prompts on error. |
| 10 | Orchestrator timeout makes morning brief slow (>5s) | Medium | Medium | Per-collector 3s timeout via `asyncio.wait_for()`. Show partial brief from available data. |
| 11 | Plugin bundle misconfiguration (wrong categories) | Medium | Low | Schema validation in `PluginLoader`. Fallback to `household` default. |
| 12 | Progressive disclosure drops context that was actually needed | Medium | Medium | Conservative heuristic (default = load everything). Monitor via Langfuse for quality drops. Easy rollback: remove heuristic check. |
| 13 | Prompt YAML variables drift from handler expectations | Medium | Medium | Template variable validation at startup. Test coverage for all prompts. CI check for YAML validity. |

---

## 15. FINAL METRICS (actual as of v4.0 — 2026-02-19)

```
                        Planned (v3.0)  Actual (v4.0)
                        ──────────────  ─────────────
Skills:                 51              61
Agents:                 12              11
Orchestrators:          4 LangGraph     2 active LangGraph (EmailOrchestrator, BriefOrchestrator)
DB Tables:              25              28
Intents:                51              61+
Channels:               4               4 (Telegram, WhatsApp, Slack, SMS)
Python files:           —               383 (255 src, 123 tests, 5 api)
Test files:             —               123 (~948 tests)
Packages:               —               ~256 (managed with uv)
Alembic migrations:     —               7 (001–007, with 006b branch)
Billing:                Stripe $49/mo   ✅ Stripe $49/mo implemented
Deploy:                 Railway         ✅ Railway + Supabase (PostgreSQL + pgvector)
CI/CD:                  GitHub Actions  ✅ lint → test → docker → Railway deploy
Star rating:            6★ MVP          6★ MVP (achieved)
```

### Dependency Summary

| Package | Phase | Purpose | License |
|---------|-------|---------|---------|
| `aiogoogle` | 2 | Async Google APIs (Gmail, Calendar) | MIT |
| `cryptography` | 2 | OAuth token encryption | Apache 2.0/BSD |
| `langgraph` | 2 | Graph-based orchestrators | MIT |
| `trafilatura` | 3 | HTML → text extraction for web search | Apache 2.0 |
| `google-genai` | 3 | Gemini API + Google Search Grounding | Apache 2.0 |
| `pyyaml` | 3.5 | YAML prompt + plugin config loading | MIT |
| `slack-bolt` | 4 | Slack channel gateway | MIT |
| `twilio` | 4 | SMS channel gateway | MIT |
| `stripe` | 4 | Subscription billing | MIT |
| `browser-use` | 5 | AI browser automation | MIT |
| `langchain-anthropic` | 5 | Browser-Use LLM backend | MIT |

---

## 16. WHAT'S NEXT

All planned phases (0–6) are implemented. Potential future work:

### Near-term improvements
- **Hybrid semantic search (Layer 6):** BM25 + pgvector RRF — column exists, logic not wired
- **Dynamic few-shot examples:** pgvector bank of examples for intent detection
- **YAML prompt migration:** Externalize remaining hardcoded prompts to `prompts.yaml`
- **Weekly digest:** Automated email/Telegram summary of spending, tasks, life events

### Medium-term features
- **Schedule C + AI auto-deductions:** Tax deduction tracking for US self-employed
- **IFTA export:** Fuel tax report for truckers
- **Per diem tracking:** Daily allowance tracking for travel
- **Excel export (openpyxl):** Download reports as .xlsx
- **Google Sheets sync:** gspread + OAuth + Taskiq for live spreadsheet sync
- **Accountant read-only access:** New role with restricted view of financial data

### Long-term vision
- **Telegram Stars monetization:** Premium reports via Telegram's in-app purchases
- **Mini App frontend SPA:** Interactive UI via Telegram Mini Apps (backend `api/miniapp.py` ready)
- **Mem0 OpenMemory MCP:** Shared memory protocol for cross-agent context
- **AI-generated YAML profiles:** Auto-create business profiles from user conversations
- **Mem0g graph memory:** Entity relationship graph across contacts, businesses, events
