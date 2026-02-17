# AI Life Assistant — Implementation Plan (Variant 3: Hybrid)

## Version: 1.0 | Date: 2026-02-17

**Approach**: Python core (75%) + OpenClaw TypeScript sidecar (25%)
**Base**: Existing Finance Bot codebase (17K lines, 22 skills, 5 agents)

---

## TABLE OF CONTENTS

1. [Phase Overview](#1-phase-overview)
2. [Phase 1: Core Generalization](#2-phase-1-core-generalization-weeks-1-2)
3. [Phase 2: Email + Calendar](#3-phase-2-email--calendar-weeks-3-4)
4. [Phase 3: Tasks + Research + Writing + CRM](#4-phase-3-tasks--research--writing--crm-weeks-5-6)
5. [Phase 4: Channels + Billing](#5-phase-4-channels--billing-weeks-7-8)
6. [Phase 5: Proactivity + Polish](#6-phase-5-proactivity--polish-weeks-9-10)
7. [Current Bugs to Fix First](#7-current-bugs-to-fix-first)
8. [File-by-File Change Map](#8-file-by-file-change-map)

---

## 1. PHASE OVERVIEW

```
Phase 1 (wk 1-2)  │ Python only │ Generalize core: multi-domain router, new DB tables
Phase 2 (wk 3-4)  │ Python only │ Email + Calendar orchestrators via Google API (direct)
Phase 3 (wk 5-6)  │ Python only │ Tasks + Research + Writing + CRM orchestrators
Phase 4 (wk 7-8)  │ + TypeScript│ OpenClaw sidecar: WhatsApp, iMessage, Slack + Stripe billing
Phase 5 (wk 9-10) │ Hybrid      │ Proactivity engine, browser automation, monitors, polish
```

---

## 2. PHASE 1: CORE GENERALIZATION (Weeks 1-2)

### 2.1 Fix existing bugs

Before any new development, fix issues in the current codebase.

#### 2.1.1 Add `query_report` to analytics agent

**File**: `src/agents/config.py:62-67`

```python
# BEFORE:
AgentConfig(
    name="analytics",
    system_prompt=ANALYTICS_AGENT_PROMPT,
    skills=["query_stats", "complex_query"],
    ...
)

# AFTER:
AgentConfig(
    name="analytics",
    system_prompt=ANALYTICS_AGENT_PROMPT,
    skills=["query_stats", "complex_query", "query_report"],
    ...
)
```

#### 2.1.2 Add missing QUERY_CONTEXT_MAP entries

**File**: `src/core/memory/context.py:49-69`

Add these 4 missing entries to `QUERY_CONTEXT_MAP`:

```python
"mark_paid":      {"mem": False,      "hist": 3, "sql": False, "sum": False},
"set_budget":     {"mem": "budgets",  "hist": 3, "sql": True,  "sum": False},
"add_recurring":  {"mem": "mappings", "hist": 3, "sql": False, "sum": False},
"scan_document":  {"mem": "mappings", "hist": 1, "sql": False, "sum": False},
```

#### 2.1.3 Remove dead `budget_advice` entry

**File**: `src/core/memory/context.py:60`

Delete the line:
```python
"budget_advice": {"mem": "all", "hist": 5, "sql": True, "sum": True},
```

---

### 2.2 Introduce domain concept

The core change: intents get a `domain` prefix for routing. Current finance intents remain backward-compatible.

#### 2.2.1 New file: `src/core/domains.py`

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

#### 2.2.2 Expand intent detection

**File**: `src/core/intent.py`

Add new intents to `INTENT_DETECTION_PROMPT`. The prompt currently lists 22 intents. We add new intents **incrementally per phase** (not all at once).

Phase 1 change — add domain hint to `IntentDetectionResult`:

**File**: `src/core/schemas/intent.py`

```python
# ADD to IntentData:
    domain: str | None = None  # finance, email, calendar, tasks, etc.

# ADD new fields for future phases:
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

#### 2.2.3 Domain router wrapper

**File**: `src/core/domain_router.py` (NEW)

This wraps the existing `AgentRouter` with domain-level routing. The existing `router.py` delegates to this instead of directly to `AgentRouter`.

```python
"""Domain-level router — sits between master_router and AgentRouter."""

from src.core.domains import Domain, INTENT_DOMAIN_MAP
from src.agents.base import AgentRouter


class DomainRouter:
    """Routes intents through domain → agent → skill pipeline.

    Phase 1: thin wrapper around AgentRouter.
    Phase 2+: each domain gets its own LangGraph orchestrator.
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
            # Phase 2+: delegate to LangGraph orchestrator
            return await orchestrator.invoke(intent, message, context, intent_data)

        # Phase 1: delegate to existing AgentRouter
        return await self._agent_router.route(intent, message, context, intent_data)
```

#### 2.2.4 Update `router.py` to use `DomainRouter`

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

All call sites in `router.py` that use `get_agent_router().route(...)` change to `get_domain_router().route(...)`. The behavior is identical in Phase 1 — `DomainRouter` passes everything through to `AgentRouter`.

---

### 2.3 New database models

#### 2.3.1 New enums

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
    imessage = "imessage"
    slack = "slack"
    discord = "discord"
    sms = "sms"
    webchat = "webchat"
```

#### 2.3.2 New model files

Each file follows the existing pattern from `src/core/models/base.py` (TimestampMixin, UUID PK, family_id FK).

| New File | Table | Key Fields |
|----------|-------|------------|
| `src/core/models/contact.py` | `contacts` | name, phone, email, role, company, tags[], last_contact_at, next_followup_at |
| `src/core/models/task.py` | `tasks` | title, status, priority, due_at, reminder_at, assigned_to (FK contacts), domain, source_message_id |
| `src/core/models/email_cache.py` | `email_cache` | gmail_id, thread_id, from_email, subject, snippet, is_read, is_important, followup_needed |
| `src/core/models/calendar_cache.py` | `calendar_cache` | google_event_id, title, start_at, end_at, attendees (JSONB), prep_notes |
| `src/core/models/monitor.py` | `monitors` | type, name, config (JSONB), check_interval_minutes, last_value (JSONB), is_active |
| `src/core/models/user_profile.py` | `user_profiles` | display_name, timezone, occupation, tone_preference, response_length, active_hours_start/end, learned_patterns (JSONB) |
| `src/core/models/usage_log.py` | `usage_logs` | domain, skill, model, tokens_input, tokens_output, cost_usd, duration_ms, success |
| `src/core/models/subscription.py` | `subscriptions` | stripe_customer_id, stripe_subscription_id, plan, status, trial_ends_at |

#### 2.3.3 Alembic migration

**File**: `alembic/versions/005_multi_domain_tables.py`

Creates all 8 new tables + RLS policies for each. Pattern from existing `002_rls_policies.py`.

#### 2.3.4 Update `src/core/models/__init__.py`

Import all new models so Alembic autogenerate picks them up.

---

### 2.4 Extend `SessionContext`

**File**: `src/core/context.py`

```python
# ADD fields to SessionContext:
    channel: str = "telegram"                  # telegram | whatsapp | imessage | slack | sms
    channel_user_id: str | None = None         # original platform user ID
    timezone: str = "America/New_York"         # user timezone
    active_domain: str | None = None           # current conversation domain
    user_profile: dict[str, Any] | None = None # learned preferences
```

---

### 2.5 Extend `IncomingMessage`

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
```

---

### 2.6 Extend `OutgoingMessage`

**File**: `src/gateway/types.py`

```python
# ADD fields to OutgoingMessage:
    channel: str = "telegram"
    requires_approval: bool = False     # user must confirm before side-effect
    approval_action: str | None = None  # what action is pending approval
    approval_data: dict | None = None   # data for the pending action
```

---

### 2.7 New dependencies (Phase 1 only)

**File**: `pyproject.toml`

```toml
# ADD under [project.dependencies]:
langgraph = ">=0.3.0"      # Graph-based orchestrators (Phase 2 uses it)
```

No other new deps in Phase 1. Google API, Stripe, Twilio added in later phases.

---

### 2.8 Update tests

**File**: `tests/test_skills/test_registry.py`

Update skill count assertion from 22 to current count (stays 22 in Phase 1, grows in Phase 2+).

**New file**: `tests/test_core/test_domains.py`

Test `INTENT_DOMAIN_MAP` covers all registered intents.

**New file**: `tests/test_core/test_domain_router.py`

Test `DomainRouter` delegates to `AgentRouter` correctly.

---

### 2.9 Phase 1 — file summary

| Action | File | Type |
|--------|------|------|
| FIX | `src/agents/config.py` | Add `query_report` to analytics agent |
| FIX | `src/core/memory/context.py` | Add 4 missing map entries, remove `budget_advice` |
| NEW | `src/core/domains.py` | Domain enum + intent→domain map |
| NEW | `src/core/domain_router.py` | Domain routing wrapper |
| EDIT | `src/core/router.py` | Use `DomainRouter` instead of `AgentRouter` directly |
| EDIT | `src/core/schemas/intent.py` | Add `domain` + future intent fields |
| EDIT | `src/core/context.py` | Add channel, timezone, active_domain fields |
| EDIT | `src/gateway/types.py` | Add channel, language, reply_to, approval fields |
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
| EDIT | `pyproject.toml` | Add `langgraph` dependency |
| NEW | `tests/test_core/test_domains.py` | Domain mapping tests |
| NEW | `tests/test_core/test_domain_router.py` | Domain router tests |
| EDIT | `tests/test_skills/test_registry.py` | Update count if needed |

**Total Phase 1**: ~8 new files, ~10 edited files

---

## 3. PHASE 2: EMAIL + CALENDAR (Weeks 3-4)

### 3.1 Google Workspace integration

Instead of using OpenClaw's `gog` skill (TypeScript/Go), we integrate Google APIs directly from Python.

#### 3.1.1 New file: `src/tools/google_workspace.py`

```python
"""Google Workspace API client — Gmail, Calendar, Contacts, Drive.

Uses google-api-python-client + google-auth-oauthlib for OAuth 2.0.
Each method is a thin wrapper around the Google API with error handling.
"""

class GoogleWorkspaceClient:
    # Gmail
    async def list_messages(self, query: str, max_results: int = 20) -> list[dict]: ...
    async def get_message(self, message_id: str) -> dict: ...
    async def get_thread(self, thread_id: str) -> list[dict]: ...
    async def send_message(self, to: str, subject: str, body: str) -> dict: ...
    async def create_draft(self, to: str, subject: str, body: str) -> dict: ...

    # Calendar
    async def list_events(self, time_min: datetime, time_max: datetime) -> list[dict]: ...
    async def create_event(self, title: str, start: datetime, end: datetime, ...) -> dict: ...
    async def update_event(self, event_id: str, **updates) -> dict: ...
    async def delete_event(self, event_id: str) -> None: ...
    async def get_free_busy(self, time_min: datetime, time_max: datetime) -> list[dict]: ...

    # Contacts (People API)
    async def search_contacts(self, query: str) -> list[dict]: ...
    async def create_contact(self, name: str, email: str = None, phone: str = None) -> dict: ...
```

#### 3.1.2 New dependency

**File**: `pyproject.toml`

```toml
google-api-python-client = ">=2.100.0"
google-auth-oauthlib = ">=1.2.0"
```

#### 3.1.3 OAuth flow

**File**: `api/oauth.py` (NEW)

```
GET /oauth/google/start   → redirect to Google consent screen
GET /oauth/google/callback → exchange code for tokens, store in DB
```

**File**: `src/core/models/oauth_token.py` (NEW)

```python
# Stores encrypted OAuth tokens per user
class OAuthToken(Base, TimestampMixin):
    id: UUID
    user_id: UUID (FK)
    provider: str  # "google"
    access_token: str (encrypted)
    refresh_token: str (encrypted)
    expires_at: datetime
    scopes: list[str]
```

---

### 3.2 Email orchestrator

#### 3.2.1 New file: `src/orchestrators/email/graph.py`

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

# Edges
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

#### 3.2.2 Email skills (5 new)

| New File | Intent | Model | Description |
|----------|--------|-------|-------------|
| `src/skills/read_inbox/handler.py` | `read_inbox` | claude-haiku-4-5 | List and summarize unread emails |
| `src/skills/send_email/handler.py` | `send_email` | claude-sonnet-4-5 | Compose and send email (requires_approval) |
| `src/skills/draft_reply/handler.py` | `draft_reply` | claude-sonnet-4-5 | Draft reply to email thread |
| `src/skills/follow_up_email/handler.py` | `follow_up_email` | claude-haiku-4-5 | Check for unanswered emails |
| `src/skills/summarize_thread/handler.py` | `summarize_thread` | claude-haiku-4-5 | Summarize email thread |

Each skill follows the existing pattern:
```
src/skills/<name>/
├── __init__.py    (empty)
└── handler.py     (class with name, intents, model, execute(), get_system_prompt())
```

#### 3.2.3 Email agent config

**File**: `src/agents/config.py` — add:

```python
EMAIL_AGENT_PROMPT = """\
You are an email assistant. Help the user manage their Gmail inbox.
Read, summarize, draft, reply, and send emails.
Always show email content in a clean format.
For sending: ALWAYS ask for user confirmation before sending.
Respond in the user's preferred language."""

AgentConfig(
    name="email",
    system_prompt=EMAIL_AGENT_PROMPT,
    skills=["read_inbox", "send_email", "draft_reply", "follow_up_email", "summarize_thread"],
    default_model="claude-sonnet-4-5",
    context_config={"mem": "profile", "hist": 5, "sql": False, "sum": False},
)
```

---

### 3.3 Calendar orchestrator

#### 3.3.1 New file: `src/orchestrators/calendar/graph.py`

```python
"""Calendar orchestrator — LangGraph StateGraph.

Nodes: planner → scheduler → conflict_checker → creator → notifier
Handles: list_events, create_event, find_free_slots, reschedule_event, morning_brief
"""
```

#### 3.3.2 Calendar skills (5 new)

| New File | Intent | Model | Description |
|----------|--------|-------|-------------|
| `src/skills/list_events/handler.py` | `list_events` | claude-haiku-4-5 | Show today/week schedule |
| `src/skills/create_event/handler.py` | `create_event` | claude-haiku-4-5 | Create calendar event (requires_approval) |
| `src/skills/find_free_slots/handler.py` | `find_free_slots` | claude-haiku-4-5 | Find available time |
| `src/skills/reschedule_event/handler.py` | `reschedule_event` | claude-haiku-4-5 | Move event (requires_approval) |
| `src/skills/morning_brief/handler.py` | `morning_brief` | claude-haiku-4-5 | Morning schedule + tasks summary |

#### 3.3.3 Calendar agent config

**File**: `src/agents/config.py` — add:

```python
CALENDAR_AGENT_PROMPT = """\
You are a calendar assistant. Help the user manage their Google Calendar.
Show schedule, create events, find free slots, reschedule.
Always check for conflicts before creating events.
For creating/modifying: ask for confirmation.
Respond in the user's preferred language."""

AgentConfig(
    name="calendar",
    system_prompt=CALENDAR_AGENT_PROMPT,
    skills=["list_events", "create_event", "find_free_slots", "reschedule_event", "morning_brief"],
    default_model="claude-haiku-4-5",
    context_config={"mem": "profile", "hist": 3, "sql": False, "sum": False},
)
```

---

### 3.4 Register orchestrators with DomainRouter

**File**: `src/core/router.py`

```python
def get_domain_router() -> DomainRouter:
    global _domain_router
    if _domain_router is None:
        agent_router = AgentRouter(AGENTS, get_registry())
        _domain_router = DomainRouter(agent_router)

        # Register LangGraph orchestrators
        from src.orchestrators.email.graph import EmailOrchestrator
        from src.orchestrators.calendar.graph import CalendarOrchestrator
        _domain_router.register_orchestrator(Domain.email, EmailOrchestrator())
        _domain_router.register_orchestrator(Domain.calendar, CalendarOrchestrator())

    return _domain_router
```

---

### 3.5 Update intent detection prompt

**File**: `src/core/intent.py`

Add 10 new intents to `INTENT_DETECTION_PROMPT`:

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

### 3.6 Update QUERY_CONTEXT_MAP

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

### 3.7 Phase 2 — file summary

| Action | File | Type |
|--------|------|------|
| NEW | `src/tools/google_workspace.py` | Google API client |
| NEW | `api/oauth.py` | OAuth endpoints |
| NEW | `src/core/models/oauth_token.py` | Token storage model |
| NEW | `alembic/versions/006_oauth_tokens.py` | Migration |
| NEW | `src/orchestrators/__init__.py` | Package init |
| NEW | `src/orchestrators/email/__init__.py` | Package init |
| NEW | `src/orchestrators/email/graph.py` | Email LangGraph |
| NEW | `src/orchestrators/email/nodes.py` | Graph nodes |
| NEW | `src/orchestrators/calendar/__init__.py` | Package init |
| NEW | `src/orchestrators/calendar/graph.py` | Calendar LangGraph |
| NEW | `src/orchestrators/calendar/nodes.py` | Graph nodes |
| NEW | `src/skills/read_inbox/` | 2 files |
| NEW | `src/skills/send_email/` | 2 files |
| NEW | `src/skills/draft_reply/` | 2 files |
| NEW | `src/skills/follow_up_email/` | 2 files |
| NEW | `src/skills/summarize_thread/` | 2 files |
| NEW | `src/skills/list_events/` | 2 files |
| NEW | `src/skills/create_event/` | 2 files |
| NEW | `src/skills/find_free_slots/` | 2 files |
| NEW | `src/skills/reschedule_event/` | 2 files |
| NEW | `src/skills/morning_brief/` | 2 files |
| EDIT | `src/skills/__init__.py` | Register 10 new skills |
| EDIT | `src/agents/config.py` | Add email + calendar agents |
| EDIT | `src/core/intent.py` | Add 10 new intents to prompt |
| EDIT | `src/core/memory/context.py` | Add 10 QUERY_CONTEXT_MAP entries |
| EDIT | `src/core/router.py` | Register email/calendar orchestrators |
| EDIT | `pyproject.toml` | Add google-api-python-client, google-auth-oauthlib |
| NEW | `tests/test_skills/test_read_inbox.py` | etc. (10 test files) |
| NEW | `tests/test_orchestrators/test_email_graph.py` | Orchestrator tests |
| NEW | `tests/test_orchestrators/test_calendar_graph.py` | Orchestrator tests |

**Total Phase 2**: ~30 new files, ~8 edited files, 10 new skills, 2 new agents

---

## 4. PHASE 3: TASKS + RESEARCH + WRITING + CRM (Weeks 5-6)

### 4.1 Task orchestrator

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/create_task/handler.py` | `create_task` | claude-haiku-4-5 |
| `src/skills/list_tasks/handler.py` | `list_tasks` | claude-haiku-4-5 |
| `src/skills/set_reminder/handler.py` | `set_reminder` | claude-haiku-4-5 |
| `src/skills/complete_task/handler.py` | `complete_task` | claude-haiku-4-5 |

Agent: `tasks` (claude-haiku-4-5)

Orchestrator: `src/orchestrators/tasks/graph.py` — simple linear graph (no multi-step planning needed for CRUD tasks).

Data: uses `tasks` table from Phase 1 migration.

---

### 4.2 Research orchestrator

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/web_search_skill/handler.py` | `web_search` | claude-sonnet-4-5 |
| `src/skills/deep_research/handler.py` | `deep_research` | claude-sonnet-4-5 |
| `src/skills/compare_options/handler.py` | `compare_options` | claude-sonnet-4-5 |

Agent: `research` (claude-sonnet-4-5)

#### Web search tool

**File**: `src/tools/web_search.py` (NEW)

Uses Brave Search API directly (no OpenClaw dependency). Simple HTTP client:

```python
class BraveSearchClient:
    """Brave Search API wrapper."""

    async def search(self, query: str, count: int = 10) -> list[SearchResult]: ...
    async def fetch_page(self, url: str) -> str: ...  # HTML → markdown
```

**Dependency**: `pyproject.toml` — add `httpx` (already present) + `BRAVE_API_KEY` env var.

---

### 4.3 Writing orchestrator

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/draft_message/handler.py` | `draft_message` | claude-sonnet-4-5 |
| `src/skills/translate_text/handler.py` | `translate_text` | claude-sonnet-4-5 |
| `src/skills/write_post/handler.py` | `write_post` | claude-sonnet-4-5 |
| `src/skills/proofread/handler.py` | `proofread` | claude-haiku-4-5 |

Agent: `writing` (claude-sonnet-4-5)

Uses `user_profiles.learned_patterns` for tone matching.

---

### 4.4 CRM / Contacts orchestrator

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/add_contact/handler.py` | `add_contact` | claude-haiku-4-5 |
| `src/skills/find_contact/handler.py` | `find_contact` | claude-haiku-4-5 |

Agent: `contacts` (claude-haiku-4-5)

Data: uses `contacts` table from Phase 1 migration.

---

### 4.5 Phase 3 — file summary

| Action | Count |
|--------|-------|
| New orchestrators | 4 (tasks, research, writing, contacts) |
| New skills | 13 |
| New agents | 4 |
| New tool files | 1 (`src/tools/web_search.py`) |
| New test files | ~17 |
| Edited files | ~8 (intent.py, config.py, context.py, registry, router, etc.) |

**Running totals after Phase 3**: 45 skills, 11 agents, 6 orchestrators

---

## 5. PHASE 4: CHANNELS + BILLING (Weeks 7-8)

### 5.1 OpenClaw sidecar setup

#### 5.1.1 Docker Compose addition

**File**: `docker-compose.yml` — add:

```yaml
  openclaw_gateway:
    image: ghcr.io/openclaw/openclaw:latest
    ports:
      - "18789:18789"
    volumes:
      - openclaw_data:/root/.openclaw
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    restart: unless-stopped
```

#### 5.1.2 Channel bridge

**File**: `src/gateway/openclaw_bridge.py` (NEW)

```python
"""Bridge between OpenClaw Gateway and our Python core.

Receives messages from OpenClaw via HTTP webhook,
converts to IncomingMessage, routes through our pipeline,
sends response back via OpenClaw API.
"""

class OpenClawBridge:
    """Adapter: OpenClaw message format → IncomingMessage → router → OutgoingMessage → OpenClaw."""

    async def on_webhook(self, raw_msg: dict) -> dict:
        """Called by FastAPI endpoint when OpenClaw forwards a message."""
        message = self._to_incoming(raw_msg)
        # Route through our standard pipeline
        result = await handle_message(message, context, gateway=self)
        return self._to_openclaw_response(result)

    def _to_incoming(self, raw: dict) -> IncomingMessage:
        """OpenClaw format → our IncomingMessage."""
        return IncomingMessage(
            id=raw["message_id"],
            user_id=raw["user_id"],
            chat_id=raw["chat_id"],
            type=self._map_type(raw["content_type"]),
            text=raw.get("text"),
            channel=raw["channel"],   # whatsapp, imessage, slack
            channel_user_id=raw["channel_user_id"],
            raw=raw,
        )
```

#### 5.1.3 Webhook endpoint

**File**: `api/main.py` — add:

```python
@app.post("/webhook/openclaw")
async def openclaw_webhook(request: Request):
    """Receive messages from OpenClaw Gateway."""
    raw_msg = await request.json()
    bridge = OpenClawBridge()
    result = await bridge.on_webhook(raw_msg)
    return result
```

---

### 5.2 WhatsApp, iMessage, Slack gateway implementations

Each channel gets a thin Python adapter that communicates with OpenClaw:

| New File | Channel | Protocol |
|----------|---------|----------|
| `src/gateway/whatsapp.py` | WhatsApp | OpenClaw Baileys via bridge |
| `src/gateway/imessage.py` | iMessage | OpenClaw BlueBubbles via bridge |
| `src/gateway/slack_gw.py` | Slack | OpenClaw Bolt via bridge |

Each implements the `MessageGateway` protocol from `src/gateway/base.py`.

---

### 5.3 Stripe billing

#### 5.3.1 New files

| File | Purpose |
|------|---------|
| `src/billing/__init__.py` | Package |
| `src/billing/stripe_client.py` | Stripe API wrapper (checkout, subscription, webhook) |
| `src/billing/usage_tracker.py` | Track LLM token usage per request |
| `src/billing/subscription.py` | Subscription CRUD, status checks |

#### 5.3.2 Usage tracking middleware

**File**: `src/core/router.py` — add post-processing:

```python
# After skill execution, log usage:
await usage_tracker.log(
    user_id=context.user_id,
    domain=domain.value,
    skill=intent,
    model=intent_data.get("_model", "unknown"),
    tokens_input=...,
    tokens_output=...,
    duration_ms=...,
)
```

#### 5.3.3 Stripe webhook

**File**: `api/main.py` — add:

```python
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription events."""
    ...
```

#### 5.3.4 New dependency

**File**: `pyproject.toml` — add `stripe>=7.0.0`

---

### 5.4 Phase 4 — file summary

| Action | Count |
|--------|-------|
| New gateway files | 4 (openclaw_bridge + 3 channel adapters) |
| New billing files | 4 |
| Docker Compose changes | 1 (add openclaw service) |
| New API endpoints | 2 (/webhook/openclaw, /webhook/stripe) |
| Edited files | ~5 |
| New test files | ~8 |

---

## 6. PHASE 5: PROACTIVITY + POLISH (Weeks 9-10)

### 6.1 Proactivity engine

| New File | Purpose |
|----------|---------|
| `src/proactivity/__init__.py` | Package |
| `src/proactivity/engine.py` | Main engine: evaluates triggers, decides actions |
| `src/proactivity/triggers.py` | Trigger definitions (morning_brief, follow_up, price_alert, etc.) |
| `src/proactivity/evaluator.py` | Condition evaluation WITHOUT LLM (pure logic) |
| `src/proactivity/scheduler.py` | Cron-like scheduler (extends existing Taskiq setup) |

Key difference from OpenClaw Heartbeat: our engine checks conditions **without LLM** first. Only generates content if a trigger fires, saving $5-30/day in LLM costs.

#### 6.1.1 Taskiq integration

**File**: `src/core/tasks/proactivity_tasks.py` (NEW)

```python
@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def evaluate_proactive_triggers():
    """Every 5 min: check all active users for proactive triggers."""
    ...
```

---

### 6.2 Monitor orchestrator

| New Skill | Intent | Model |
|-----------|--------|-------|
| `src/skills/price_alert/handler.py` | `price_alert` | claude-haiku-4-5 |
| `src/skills/news_monitor/handler.py` | `news_monitor` | claude-haiku-4-5 |

Uses `monitors` table + `web_search` tool + Taskiq cron.

---

### 6.3 Action approval system

**File**: `src/core/approval.py` (NEW)

For actions that require user confirmation (send_email, create_event, book_restaurant):

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

Integrates with existing callback handling in `router.py`.

---

### 6.4 User profile auto-learning

**File**: `src/core/tasks/profile_tasks.py` (NEW)

```python
@broker.task(schedule=[{"cron": "0 3 * * *"}])
async def update_user_profiles():
    """Daily: analyze last 50 messages per user, update learned_patterns."""
    ...
```

---

### 6.5 Onboarding expansion (English + multi-domain)

**File**: `src/skills/onboarding/handler.py` — edit:

- Support English onboarding flow (detect language from first message)
- Ask about connected services (Gmail, Calendar) instead of just business type
- Guide through OAuth connection

---

### 6.6 Phase 5 — file summary

| Action | Count |
|--------|-------|
| New proactivity files | 5 |
| New monitor skills | 2 |
| New approval system | 1 |
| New profile learning task | 1 |
| Edited onboarding | 1 |
| New test files | ~6 |

---

## 7. CURRENT BUGS TO FIX FIRST

These should be fixed **before** starting Phase 1 new development.

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

## 8. FILE-BY-FILE CHANGE MAP

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
[EDIT] src/core/router.py                          # Use DomainRouter
[EDIT] src/core/schemas/intent.py                  # Add domain + future fields
[EDIT] src/core/context.py                         # Add channel, timezone, profile
[EDIT] src/gateway/types.py                        # Add channel, language, approval
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
[NEW]  alembic/versions/005_multi_domain_tables.py # Migration for 8 new tables
[EDIT] pyproject.toml                              # Add langgraph
[NEW]  tests/test_core/test_domains.py             # Domain mapping tests
[NEW]  tests/test_core/test_domain_router.py       # Domain router tests

═══════════════════════════════════════════════════════════════
PHASE 2: EMAIL + CALENDAR (Weeks 3-4)
═══════════════════════════════════════════════════════════════
[NEW]  src/tools/google_workspace.py               # Google API client
[NEW]  api/oauth.py                                # Google OAuth endpoints
[NEW]  src/core/models/oauth_token.py              # OAuth token model
[NEW]  alembic/versions/006_oauth_tokens.py        # Migration
[NEW]  src/orchestrators/__init__.py               # Package init
[NEW]  src/orchestrators/base.py                   # Base orchestrator protocol
[NEW]  src/orchestrators/email/__init__.py         #
[NEW]  src/orchestrators/email/graph.py            # Email LangGraph StateGraph
[NEW]  src/orchestrators/email/nodes.py            # Planner, reader, writer, reviewer, sender
[NEW]  src/orchestrators/email/state.py            # EmailState TypedDict
[NEW]  src/orchestrators/calendar/__init__.py      #
[NEW]  src/orchestrators/calendar/graph.py         # Calendar LangGraph StateGraph
[NEW]  src/orchestrators/calendar/nodes.py         # Scheduler, conflict checker, creator
[NEW]  src/orchestrators/calendar/state.py         # CalendarState TypedDict
[NEW]  src/skills/read_inbox/__init__.py           #
[NEW]  src/skills/read_inbox/handler.py            # Read inbox skill
[NEW]  src/skills/send_email/__init__.py           #
[NEW]  src/skills/send_email/handler.py            # Send email skill
[NEW]  src/skills/draft_reply/__init__.py          #
[NEW]  src/skills/draft_reply/handler.py           # Draft reply skill
[NEW]  src/skills/follow_up_email/__init__.py      #
[NEW]  src/skills/follow_up_email/handler.py       # Follow-up skill
[NEW]  src/skills/summarize_thread/__init__.py     #
[NEW]  src/skills/summarize_thread/handler.py      # Summarize thread skill
[NEW]  src/skills/list_events/__init__.py          #
[NEW]  src/skills/list_events/handler.py           # List events skill
[NEW]  src/skills/create_event/__init__.py         #
[NEW]  src/skills/create_event/handler.py          # Create event skill
[NEW]  src/skills/find_free_slots/__init__.py      #
[NEW]  src/skills/find_free_slots/handler.py       # Find free slots skill
[NEW]  src/skills/reschedule_event/__init__.py     #
[NEW]  src/skills/reschedule_event/handler.py      # Reschedule event skill
[NEW]  src/skills/morning_brief/__init__.py        #
[NEW]  src/skills/morning_brief/handler.py         # Morning brief skill
[EDIT] src/skills/__init__.py                      # Register 10 new skills
[EDIT] src/agents/config.py                        # Add email + calendar agents (7 total)
[EDIT] src/core/intent.py                          # Add 10 intents to prompt (32 total)
[EDIT] src/core/memory/context.py                  # Add 10 QUERY_CONTEXT_MAP entries
[EDIT] src/core/router.py                          # Register email/calendar orchestrators
[EDIT] pyproject.toml                              # Add google-api-python-client, google-auth
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
[NEW]  tests/test_orchestrators/test_calendar_graph.py #

═══════════════════════════════════════════════════════════════
PHASE 3: TASKS + RESEARCH + WRITING + CRM (Weeks 5-6)
═══════════════════════════════════════════════════════════════
[NEW]  src/tools/web_search.py                     # Brave Search API client
[NEW]  src/orchestrators/tasks/__init__.py         #
[NEW]  src/orchestrators/tasks/graph.py            # Tasks LangGraph
[NEW]  src/orchestrators/research/__init__.py      #
[NEW]  src/orchestrators/research/graph.py         # Research LangGraph
[NEW]  src/orchestrators/writing/__init__.py       #
[NEW]  src/orchestrators/writing/graph.py          # Writing LangGraph
[NEW]  src/orchestrators/contacts/__init__.py      #
[NEW]  src/orchestrators/contacts/graph.py         # Contacts LangGraph
[NEW]  src/skills/create_task/__init__.py          #
[NEW]  src/skills/create_task/handler.py           #
[NEW]  src/skills/list_tasks/__init__.py           #
[NEW]  src/skills/list_tasks/handler.py            #
[NEW]  src/skills/set_reminder/__init__.py         #
[NEW]  src/skills/set_reminder/handler.py          #
[NEW]  src/skills/complete_task/__init__.py        #
[NEW]  src/skills/complete_task/handler.py         #
[NEW]  src/skills/web_search_skill/__init__.py     #
[NEW]  src/skills/web_search_skill/handler.py      #
[NEW]  src/skills/deep_research/__init__.py        #
[NEW]  src/skills/deep_research/handler.py         #
[NEW]  src/skills/compare_options/__init__.py      #
[NEW]  src/skills/compare_options/handler.py       #
[NEW]  src/skills/draft_message/__init__.py        #
[NEW]  src/skills/draft_message/handler.py         #
[NEW]  src/skills/translate_text/__init__.py       #
[NEW]  src/skills/translate_text/handler.py        #
[NEW]  src/skills/write_post/__init__.py           #
[NEW]  src/skills/write_post/handler.py            #
[NEW]  src/skills/proofread/__init__.py            #
[NEW]  src/skills/proofread/handler.py             #
[NEW]  src/skills/add_contact/__init__.py          #
[NEW]  src/skills/add_contact/handler.py           #
[NEW]  src/skills/find_contact/__init__.py         #
[NEW]  src/skills/find_contact/handler.py          #
[EDIT] src/skills/__init__.py                      # Register 13 new skills (45 total)
[EDIT] src/agents/config.py                        # Add 4 agents (11 total)
[EDIT] src/core/intent.py                          # Add 13 intents (45 total)
[EDIT] src/core/memory/context.py                  # Add 13 QUERY_CONTEXT_MAP entries
[EDIT] src/core/router.py                          # Register 4 orchestrators
[EDIT] src/core/domains.py                         # Verify all new intents mapped
[NEW]  tests/test_skills/test_create_task.py       #
[NEW]  tests/test_skills/test_list_tasks.py        #
[NEW]  tests/test_skills/test_set_reminder.py      #
[NEW]  tests/test_skills/test_complete_task.py     #
[NEW]  tests/test_skills/test_web_search_skill.py  #
[NEW]  tests/test_skills/test_deep_research.py     #
[NEW]  tests/test_skills/test_compare_options.py   #
[NEW]  tests/test_skills/test_draft_message.py     #
[NEW]  tests/test_skills/test_translate_text.py    #
[NEW]  tests/test_skills/test_write_post.py        #
[NEW]  tests/test_skills/test_proofread.py         #
[NEW]  tests/test_skills/test_add_contact.py       #
[NEW]  tests/test_skills/test_find_contact.py      #
[NEW]  tests/test_orchestrators/test_tasks_graph.py     #
[NEW]  tests/test_orchestrators/test_research_graph.py  #
[NEW]  tests/test_orchestrators/test_writing_graph.py   #
[NEW]  tests/test_orchestrators/test_contacts_graph.py  #

═══════════════════════════════════════════════════════════════
PHASE 4: CHANNELS + BILLING (Weeks 7-8)
═══════════════════════════════════════════════════════════════
[NEW]  src/gateway/openclaw_bridge.py              # OpenClaw ↔ Python bridge
[NEW]  src/gateway/whatsapp.py                     # WhatsApp adapter
[NEW]  src/gateway/imessage.py                     # iMessage adapter
[NEW]  src/gateway/slack_gw.py                     # Slack adapter
[NEW]  src/billing/__init__.py                     #
[NEW]  src/billing/stripe_client.py                # Stripe API wrapper
[NEW]  src/billing/usage_tracker.py                # Token usage logging
[NEW]  src/billing/subscription.py                 # Subscription management
[EDIT] api/main.py                                 # Add /webhook/openclaw, /webhook/stripe
[EDIT] docker-compose.yml                          # Add openclaw_gateway service
[EDIT] pyproject.toml                              # Add stripe
[NEW]  tests/test_gateway/test_openclaw_bridge.py  #
[NEW]  tests/test_gateway/test_whatsapp.py         #
[NEW]  tests/test_billing/test_stripe_client.py    #
[NEW]  tests/test_billing/test_usage_tracker.py    #

═══════════════════════════════════════════════════════════════
PHASE 5: PROACTIVITY + POLISH (Weeks 9-10)
═══════════════════════════════════════════════════════════════
[NEW]  src/proactivity/__init__.py                 #
[NEW]  src/proactivity/engine.py                   # Main proactivity engine
[NEW]  src/proactivity/triggers.py                 # Trigger definitions
[NEW]  src/proactivity/evaluator.py                # Condition evaluation (no LLM)
[NEW]  src/proactivity/scheduler.py                # Scheduler (Taskiq integration)
[NEW]  src/core/tasks/proactivity_tasks.py         # Cron tasks
[NEW]  src/core/tasks/profile_tasks.py             # User profile auto-learning
[NEW]  src/core/approval.py                        # Action approval system
[NEW]  src/skills/price_alert/__init__.py          #
[NEW]  src/skills/price_alert/handler.py           #
[NEW]  src/skills/news_monitor/__init__.py         #
[NEW]  src/skills/news_monitor/handler.py          #
[EDIT] src/skills/__init__.py                      # Register 2 skills (47 total)
[EDIT] src/agents/config.py                        # Add monitor agent (12 total)
[EDIT] src/core/intent.py                          # Add 2 intents (47 total)
[EDIT] src/core/router.py                          # Integrate approval + usage tracking
[EDIT] src/skills/onboarding/handler.py            # English + multi-domain onboarding
[NEW]  tests/test_proactivity/test_engine.py       #
[NEW]  tests/test_proactivity/test_triggers.py     #
[NEW]  tests/test_proactivity/test_evaluator.py    #
[NEW]  tests/test_skills/test_price_alert.py       #
[NEW]  tests/test_skills/test_news_monitor.py      #
```

---

## FINAL METRICS

```
                        Before          After Phase 5
                        ──────          ──────────────
Skills:                 22              47
Agents:                 5               12
Orchestrators:          0               8 (LangGraph)
DB Tables:              15              24
Intents:                22              47
Channels:               1 (Telegram)    5 (TG, WA, iMsg, Slack, SMS)
New Python files:       0               ~110
Edited Python files:    0               ~15
New test files:         0               ~55
Dependencies added:     0               4 (langgraph, google-api, google-auth, stripe)
```
