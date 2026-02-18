# Platform Architecture: Declarative Skills, Connector Registry, Plugin Bundles, Orchestrator, Smart Context

**Author:** AI Assistant
**Date:** 2026-02-18
**Status:** Draft
**Star Rating:** 5★ → 7★ (transforms hardcoded bot into extensible platform with cross-domain intelligence)
**RICE Score:** 52.8 (Reach 100% x Impact 3.5 x Confidence 80% / Effort 5.3 wks)
**Inspired by:** Claude Cowork plugin architecture, Agent Teams orchestration patterns

---

## 1. Problem Statement

### What problem are we solving?

The bot has 43 skills but every new skill requires editing 7+ Python files. System prompts are hardcoded in handlers — iterating tone or language requires code deployment. External integrations (Gmail, Calendar, future Slack/WhatsApp) are wired directly into skill handlers with no shared abstraction. Morning brief, the flagship proactive feature, generates hallucinated data because it can't pull from calendar, tasks, and email simultaneously. And every intent loads the same amount of context regardless of query complexity, wasting tokens on "100р кофе" the same as "analyze my spending trends for Q1."

### The Maria Test

> Maria says "what's my day look like?" and expects one message combining: Emma's 3:15 pickup, Noah's soccer at 5, dentist at 2, the grocery delivery between 4-6, and her 3 overdue tasks. Instead she gets a generic hallucinated schedule because `morning_brief` can't access calendar, tasks, or email data. She has to ask three separate questions to piece together her day — exactly the experience she's trying to escape by paying $49/month.

### The David Test

> David runs a plumbing business. His expense categories should be "Materials", "Gas", "Vehicle", "Subcontractor" — not "Groceries" and "Entertainment." When he adds an expense, the bot should say "Materials — $47 at Home Depot" not "Shopping — $47." But customizing the experience per business type requires a developer to modify Python code. David also needs a morning brief that shows: today's jobs, outstanding invoices, and supply orders — not the same generic brief Maria gets.

### Who else has this problem?

100% of users hit the prompt iteration bottleneck (prompts buried in Python). 100% of users who use morning brief get hallucinated data. 80% of business users need customized categories and workflows. Every future integration (Slack, WhatsApp, Stripe, CRM) will duplicate the same OAuth/API plumbing unless we build a shared connector layer now.

---

## 2. Solution Overview

### What are we building?

Five architectural capabilities that transform the bot from a hardcoded skill collection into an extensible platform:

1. **YAML Prompt System** — externalize all system prompts into YAML files alongside handlers
2. **Connector Registry** — unified abstraction for external service connections (Google, Slack, Stripe, etc.)
3. **Plugin Bundles** — self-contained business profile packages with custom prompts, categories, reports
4. **Multi-Agent Orchestrator** — parallel skill execution for cross-domain queries (morning brief, evening recap)
5. **Progressive Context Disclosure** — load context layers dynamically based on query complexity

### Conversation Example — Orchestrated Morning Brief

**Maria's scenario (after implementation):**
```
[7:00 AM — proactive push]
Bot: Morning, Maria. Here's your Tuesday:

📅 Schedule:
• 10:00 — Emma's dentist (Dr. Park, 45 min)
• 2:00 — Call with school re: Noah's field trip
• 3:15 — Pick up Emma

✅ Tasks (3 open):
• [urgent] Sign Noah's permission slip — due today
• Buy Emma's birthday present
• Grocery order for Saturday

📧 Email:
• 2 need replies: Dr. Park's office (reschedule?), Emma's teacher (field trip form)

Want me to draft a reply to Dr. Park?
```

**David's scenario (with business plugin):**
```
[6:30 AM — proactive push]
Bot: Morning, David. Your Tuesday:

🔧 Jobs:
• 8:00 — Oak Ave bathroom (Mike + Jose)
• 11:30 — Queens Blvd kitchen estimate
• 2:00 — Mrs. Chen follow-up call

💰 Money:
• Yesterday: $385 in materials, $1,200 invoiced
• Outstanding: $2,450 across 3 invoices (Mrs. Chen: 12 days overdue)

📧 Email:
• Supplier quote from Ferguson — $127 for PVC fittings
• Mrs. Chen replied about payment

Reply to Ferguson or call Mrs. Chen first?
```

### What are we NOT building?

1. Visual plugin editor / marketplace — file-based YAML only
2. User-facing skill creation ("create a skill for me") — admin-only in this phase
3. Dynamic model routing per plugin — uses existing TASK_MODEL_MAP
4. Real-time collaboration between multiple bot instances — single-tenant architecture stays
5. Connector SDK for third-party developers — internal connectors only

---

## 3. User Stories

### P0 — Must Have

| # | Story | Acceptance Criteria |
|---|-------|-------------------|
| 1 | As a developer, I can change a skill's system prompt by editing a YAML file without touching Python | YAML file loaded at runtime; Python handler uses `load_prompt()` helper |
| 2 | As a user, morning brief shows real data from calendar + tasks + email | Orchestrator calls 3+ skills in parallel via `asyncio.gather()` |
| 3 | As a developer, I add a new external service by creating one connector file + config entry | `BaseConnector` protocol with `connect/disconnect/get_client` |
| 4 | As a user, simple messages ("100р кофе") get fast responses without loading unnecessary context | Heuristic skip of Mem0/SQL for simple patterns; measurable token reduction |

### P1 — Should Have

| # | Story | Acceptance Criteria |
|---|-------|-------------------|
| 5 | As a business owner, my bot has categories and prompts specific to my business type | Plugin bundle loaded from `config/plugins/{type}/` at onboarding |
| 6 | As a user, evening recap summarizes my day (tasks done, spending, events attended) | `evening_recap` orchestrator skill with parallel data collection |
| 7 | As a developer, skill metadata (name, intents, model) is declared in YAML, not only in Python | `prompts.yaml` contains `name`, `intents`, `model` fields; `SkillRegistry` can auto-discover from YAML |

### P2 — Nice to Have

| # | Story | Acceptance Criteria |
|---|-------|-------------------|
| 8 | As a developer, I can A/B test prompt variants via YAML `variants` field | Variant selection logic in `load_prompt()`; logging to Langfuse |
| 9 | As a PM, I can see token savings from progressive disclosure in usage dashboards | `usage_logs` tracks `context_tokens_saved` field |

### Won't Have

- Plugin marketplace or sharing between tenants
- LLM-based context assessment for simple queries (heuristic only in this phase)
- Hot-reload of YAML without restart (read at startup is sufficient)

---

## 4. Success Metrics

### Primary Metrics

| Metric | Current | Target | How Measured |
|--------|---------|--------|-------------|
| Morning brief data accuracy | 0% (hallucinated) | 95%+ (real data) | Manual QA + user reports |
| Time to add new skill | ~2 hours (7 files) | ~30 min (YAML + handler) | Developer survey |
| Time to iterate prompt | ~20 min (PR + deploy) | ~2 min (edit YAML + restart) | Developer survey |
| Token usage per simple query | ~3K tokens | ~500 tokens | `usage_logs` avg for simple intents |
| Business profile satisfaction | N/A | 4.5+/5 survey score | Onboarding exit survey |

### Leading Indicators

- Prompt YAML files created for >80% of skills within 2 weeks
- Connector registry used by all Phase 4 integrations (no direct API imports in handlers)
- Morning brief retention: users who receive it daily churn 40% less

### Failure Signals

- YAML parsing errors in production (>0.1% of requests) → need validation on startup
- Orchestrator timeout (>5s for morning brief) → need parallel execution + per-skill timeout
- Plugin bundle not found at onboarding → fallback to `household` default

---

## 5. Technical Specification

### 5.1 YAML Prompt System

**File structure per skill:**
```
src/skills/{name}/
├── __init__.py
├── handler.py      # Python logic (unchanged execute signature)
└── prompts.yaml    # NEW: externalized prompts + metadata
```

**`prompts.yaml` schema:**
```yaml
name: list_events                    # skill name
description: Shows calendar events   # for auto-discovery
model: claude-haiku-4-5             # default model
intents:                             # triggers
  - list_events

system_prompt: |
  You are a calendar assistant for {user_name}.
  Language: {language}.
  ...

variants:                            # A/B testing (P2)
  empty: "Your calendar is clear for {period}."
  busy: "Packed day — {event_count} events."
```

**Loader (`src/skills/prompt_loader.py`):**
```python
_cache: dict[str, dict] = {}

def load_prompt(skill_dir: Path) -> dict:
    if skill_dir not in _cache:
        yaml_path = skill_dir / "prompts.yaml"
        if yaml_path.exists():
            _cache[skill_dir] = yaml.safe_load(yaml_path.read_text())
        else:
            _cache[skill_dir] = {}
    return _cache[skill_dir]
```

**Migration path:** Gradual — skills work without `prompts.yaml` (use hardcoded prompts). As YAML files are added, `get_system_prompt()` checks YAML first.

### 5.2 Connector Registry

**Directory:**
```
src/core/connectors/
├── __init__.py         # ConnectorRegistry singleton
├── base.py             # BaseConnector protocol
├── google.py           # Google OAuth (Gmail + Calendar)
├── slack.py            # Slack OAuth
├── stripe.py           # Stripe API key
├── whatsapp.py         # WhatsApp token
└── config.yaml         # Declarative config
```

**BaseConnector protocol:**
```python
class BaseConnector(Protocol):
    name: str
    is_configured: bool   # env vars present?

    async def connect(self, user_id: str) -> str:
        """Returns auth URL or confirmation."""
        ...
    async def disconnect(self, user_id: str) -> bool: ...
    async def is_connected(self, user_id: str) -> bool: ...
    async def get_client(self, user_id: str) -> Any:
        """Returns ready-to-use API client with valid tokens."""
        ...
    async def refresh_if_needed(self, user_id: str) -> None: ...
```

**ConnectorRegistry:**
```python
class ConnectorRegistry:
    _connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None: ...
    def get(self, name: str) -> BaseConnector | None: ...
    def list_configured(self) -> list[str]: ...
    def list_connected(self, user_id: str) -> list[str]: ...
```

**config.yaml:**
```yaml
connectors:
  google:
    type: oauth2
    scopes:
      gmail: [gmail.readonly, gmail.send, gmail.modify]
      calendar: [calendar.events, calendar.readonly]
    encryption: true
  slack:
    type: oauth2
    scopes: [channels:read, chat:write, users:read]
  stripe:
    type: api_key
    env_var: STRIPE_SECRET_KEY
  whatsapp:
    type: api_key
    env_var: WHATSAPP_API_TOKEN
```

**Impact on skills:** `read_inbox` changes from importing `aiogoogle` directly to:
```python
google = connector_registry.get("google")
if not await google.is_connected(context.user_id):
    return SkillResult(response_text="Connect Gmail first.",
                       buttons=[{"text": "Connect", "url": await google.connect(context.user_id)}])
client = await google.get_client(context.user_id)
```

### 5.3 Plugin Bundles for Business Profiles

**Directory:**
```
config/plugins/
├── household/          # default
│   └── plugin.yaml
├── restaurant/
│   ├── plugin.yaml
│   └── prompts/
│       ├── add_expense.yaml
│       └── query_report.yaml
├── taxi/
│   ├── plugin.yaml
│   └── prompts/
│       └── add_expense.yaml
├── plumber/
│   ├── plugin.yaml
│   └── prompts/
│       └── add_expense.yaml
│       └── query_report.yaml
└── ...
```

**`plugin.yaml` schema:**
```yaml
name: plumber
display_name: "Plumbing & Trades"
description: "For plumbers, electricians, and trade businesses"

categories:
  - { name: "Materials", icon: "🔧", keywords: ["home depot", "ferguson", "pvc", "copper"] }
  - { name: "Vehicle", icon: "🚐", keywords: ["gas", "oil change", "tires"] }
  - { name: "Subcontractor", icon: "👷", keywords: ["helper", "apprentice"] }
  - { name: "Tools", icon: "🛠️", keywords: ["milwaukee", "dewalt", "drill"] }

metrics:
  - revenue_per_job
  - materials_percentage
  - outstanding_invoices

morning_brief_sections:
  - jobs_today        # from tasks + calendar
  - money_summary     # from analytics
  - outstanding       # invoices overdue
  - email_highlights  # important emails

disabled_skills: []   # all enabled by default
```

**Loader (`src/core/plugin_loader.py`):**
```python
class PluginLoader:
    def load(self, plugin_name: str) -> PluginConfig: ...
    def get_prompt_override(self, plugin_name: str, skill_name: str) -> str | None: ...
    def get_categories(self, plugin_name: str) -> list[dict]: ...
    def get_morning_brief_sections(self, plugin_name: str) -> list[str]: ...
```

**Integration point:** `SessionContext` already has `categories`. Plugin loader populates this at context creation based on user's profile type.

### 5.4 Multi-Agent Orchestrator

**New skill: `src/skills/morning_brief/handler.py` (rewrite)**

```python
class MorningBriefSkill:
    name = "morning_brief"
    intents = ["morning_brief"]
    model = "claude-sonnet-4-5"  # upgraded for synthesis

    async def execute(self, message, context, intent_data) -> SkillResult:
        plugin = plugin_loader.load(context.profile_type or "household")
        sections = plugin.get_morning_brief_sections()

        # Parallel data collection
        collectors = {
            "jobs_today": self._collect_events(context),
            "tasks": self._collect_tasks(context),
            "money_summary": self._collect_finance(context),
            "email_highlights": self._collect_emails(context),
            "outstanding": self._collect_invoices(context),
        }

        # Only run sections configured in plugin
        active = {k: v for k, v in collectors.items() if k in sections}
        results = await asyncio.gather(
            *active.values(),
            return_exceptions=True
        )
        data = {k: r for k, r in zip(active.keys(), results) if not isinstance(r, Exception)}

        # Synthesize with LLM
        brief = await self._synthesize(data, context)
        return SkillResult(response_text=brief)

    async def _collect_events(self, ctx) -> str:
        google = connector_registry.get("google")
        if not await google.is_connected(ctx.user_id):
            return "Calendar not connected."
        client = await google.get_client(ctx.user_id)
        events = await client.list_events(today_start, today_end)
        return format_events_brief(events)

    async def _collect_tasks(self, ctx) -> str:
        tasks = await get_open_tasks(ctx.family_id, ctx.user_id)
        return format_tasks_brief(tasks)

    async def _collect_finance(self, ctx) -> str:
        # yesterday's spending summary from DB
        ...

    async def _collect_emails(self, ctx) -> str:
        google = connector_registry.get("google")
        if not await google.is_connected(ctx.user_id):
            return "Email not connected."
        client = await google.get_client(ctx.user_id)
        emails = await client.list_messages("is:unread is:important", max_results=5)
        return format_email_brief(emails)
```

**New skill: `evening_recap` (same pattern)**
- Collects: tasks completed today, spending total, events attended, mood (if tracked)
- Plugin config determines sections

**Timeout handling:** Each collector has 3s timeout via `asyncio.wait_for()`. Failed collectors return fallback text ("Calendar data unavailable"), brief still generates from available data.

### 5.5 Progressive Context Disclosure

**Location:** `src/core/memory/context.py` — modify `assemble_context()`

**Phase 1 — Regex heuristic (no LLM cost):**

```python
import re

SIMPLE_PATTERNS = [
    r"^\d+[\s.,]?\s?\w{1,20}$",           # "100 кофе", "50.5 uber"
    r"^(да|нет|ок|ok|спасибо|thanks|thx)",  # confirmations
    r"^(привет|hello|hi|hey)\b",            # greetings
    r"^(готово|done|сделано)\b",            # completions
]

COMPLEX_SIGNALS = [
    "сравни", "compare", "тренд", "trend", "обычно", "usually",
    "прошлый", "last", "бюджет", "budget", "итого", "total",
    "за месяц", "за неделю", "this month", "this week",
]

def _needs_heavy_context(message: str, intent: str) -> bool:
    text = message.strip().lower()

    # Always heavy for analytics intents
    if intent in ("query_stats", "complex_query", "query_report"):
        return True

    # Simple patterns → skip heavy context
    if any(re.match(p, text, re.I) for p in SIMPLE_PATTERNS):
        return False

    # Complex signals → load everything
    if any(s in text for s in COMPLEX_SIGNALS):
        return True

    # Default: follow QUERY_CONTEXT_MAP as-is
    return True
```

**Integration into `assemble_context()`:**
```python
async def assemble_context(...):
    config = QUERY_CONTEXT_MAP.get(intent, DEFAULT_CONFIG)

    if not _needs_heavy_context(current_message, intent):
        config = {**config, "mem": False, "sql": False, "sum": False, "hist": min(config.get("hist", 0), 1)}

    # rest of assembly unchanged
```

**Token savings tracking:**
```python
saved = original_tokens - actual_tokens
await log_usage(..., context_tokens_saved=saved)
```

---

## 6. Proactivity Design

### Morning Brief (Orchestrator)
- **Trigger:** TimeTrigger at user's preferred wake time (default 7:00 AM)
- **Frequency:** Once daily, skip weekends if user preference
- **Channel:** Primary channel (Telegram by default)
- **Graceful degradation:** If calendar not connected → skip calendar section, still show tasks + finance

### Evening Recap (Orchestrator)
- **Trigger:** TimeTrigger at user's preferred wind-down time (default 9:00 PM)
- **Frequency:** Once daily
- **Content:** Day summary, not action items — "wrap up" tone

### Smart Context Adaptation
- After 100 messages per user: log `_needs_heavy_context` hit rate
- If >80% of a user's messages are simple → cache their default as "light context"

---

## 7. Risks & Mitigations

| # | Risk | Impact | Probability | Mitigation |
|---|------|--------|-------------|------------|
| 1 | YAML parsing errors crash skill loading | High | Low | Validate all YAML at startup; fall back to hardcoded prompts on error |
| 2 | Orchestrator timeout (>5s) makes morning brief feel slow | Medium | Medium | Per-collector 3s timeout; show partial brief from available data |
| 3 | Plugin bundle misconfiguration (wrong categories) | Medium | Low | Schema validation in `PluginLoader`; `household` fallback |
| 4 | Connector registry adds indirection that slows API calls | Low | Low | Minimal wrapper; `get_client()` returns raw API client |
| 5 | Progressive disclosure drops context that was actually needed | Medium | Medium | Conservative heuristic (default = load); monitor via Langfuse for quality drops |
| 6 | YAML prompt diverges from handler expectations (wrong variables) | Medium | Medium | Template variable validation at startup; test coverage for all prompts |

---

## 8. Timeline

| Week | Deliverable | Files | Dependencies |
|------|-------------|-------|-------------|
| 1 | YAML Prompt System — loader, migration of 10 key skills | ~15 | None |
| 2 | Connector Registry — base + Google connector (refactor existing OAuth) | ~10 | None (parallel with week 1) |
| 3 | Plugin Bundles — loader + 3 plugins (household, plumber, restaurant) | ~12 | YAML prompts |
| 4 | Orchestrator — morning_brief rewrite + evening_recap | ~8 | Connectors, list_tasks |
| 5 | Progressive Disclosure — heuristic + metrics | ~4 | None |
| 5 | Integration testing + prompt tuning | ~6 tests | All above |

**Total:** ~55 files (new + edited), 5.3 weeks estimated

---

## Self-Score (PRD Rubric)

| Criterion | Score (1-5) | Weight | Weighted |
|-----------|------------|--------|----------|
| Problem Clarity | 5 | 2.0x | 10.0 |
| User Stories | 4 | 1.5x | 6.0 |
| Success Metrics | 4 | 1.5x | 6.0 |
| Scope Definition | 5 | 1.0x | 5.0 |
| Technical Feasibility | 4 | 1.0x | 4.0 |
| Risk Assessment | 4 | 1.0x | 4.0 |
| **Total** | | | **35.0 → normalized 26.3/30** |

**Verdict:** Ready to build (25+/30)

---

## Auto-Check Checklist

- [x] Maria test included with specific scenario
- [x] David test included with specific scenario
- [x] Star rating stated (5→7)
- [x] RICE score calculated (52.8)
- [x] "Not building" list defined (5 items)
- [x] Success metrics have current vs target
- [x] Failure signals defined
- [x] Cost impact considered (token savings via progressive disclosure)
- [x] Proactivity design section included
- [x] Timeline with weekly deliverables
- [x] Rubric self-score ≥25/30
