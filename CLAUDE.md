# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (uses uv)
uv sync

# Lint
ruff check src/ api/ tests/

# Format
ruff format src/ api/ tests/

# Run all tests
pytest tests/ -x -q --tb=short

# Run a single test file
pytest tests/test_skills/test_track_drink.py -v

# Run a specific test
pytest tests/test_skills/test_track_drink.py::test_keyword_coffee_detected -v

# Run with coverage
pytest tests/ --cov=src --cov-report=xml

# Database migration
alembic upgrade head

# Dev server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Task queue worker (full command with all task modules)
TASK_MODULES="src.core.tasks.memory_tasks src.core.tasks.notification_tasks src.core.tasks.life_tasks src.core.tasks.reminder_tasks src.core.tasks.profile_tasks src.core.tasks.proactivity_tasks src.core.tasks.booking_tasks src.core.tasks.document_tasks src.core.tasks.crossdomain_tasks"
python -m taskiq worker src.core.tasks.broker:broker $TASK_MODULES

# Task queue scheduler (separate process, needed for cron tasks)
python -m taskiq scheduler src.core.tasks.broker:scheduler $TASK_MODULES

# Deploy to Railway (manual)
railway up -d
```

**Ruff config**: Python 3.12+, line-length 100, rules: E, F, I, N, W, UP.

## Architecture

### Message Flow

```
Telegram/Slack/WhatsApp/SMS webhook
  → api/main.py
  → src/core/router.py builds SessionContext
  → src/core/rate_limiter.py tiered rate check (Redis INCR+EXPIRE)
  → src/core/guardrails.py input safety check (Claude Haiku)
  → src/core/intent.py detects intent (Gemini Flash primary, Claude Haiku fallback)
  → CLARIFY gate: if ambiguous → disambiguation buttons via Redis
  → src/core/domain_router.py checks for orchestrator (email, brief domains)
    → If orchestrator registered → LangGraph graph.invoke()
    → Else → src/agents/base.py:AgentRouter
  → src/core/memory/context.py assembles multi-layer context with token budget
  → skill.execute() → SkillResult
  → Background tasks (Mem0 update, merchant mapping, budget check)
  → gateway.send() → Telegram/Slack/WhatsApp/SMS
```

### Key Abstractions

- **SessionContext** (`src/core/context.py`): Immutable per-request context. Core fields: `user_id`, `family_id`, `role` (owner/member), `language`, `currency`, `business_type`, `categories`, `merchant_mappings`, `profile_config`, `channel`, `timezone`, `user_profile`. Enforces multi-tenant isolation via `filter_query()`.
- **AgentConfig** (`src/agents/config.py`): 13 agents, each with system prompt, model, skill list, and `context_config` dict (`mem`/`hist`/`sql`/`sum` — which memory layers to load).
- **BaseSkill** protocol (`src/skills/base.py`): `name`, `intents[]`, `model`, `execute(message, context, intent_data) → SkillResult`, `get_system_prompt(context)`.
- **SkillResult** (`src/skills/base.py`): `response_text` + optional `buttons`, `document`, `document_name`, `photo_url`, `photo_bytes`, `chart_url`, `reply_keyboard`, `background_tasks`.
- **SkillRegistry** (`src/skills/__init__.py`): Maps intent strings to skill instances. `get(intent) → skill`. Currently 93 skills registered.
- **DomainRouter** (`src/core/domain_router.py`): Routes intents to LangGraph orchestrators or AgentRouter. Orchestrators registered: email, brief, booking (if `ff_langgraph_booking`). Approval orchestrator invoked directly via `start_approval()`.

### Model Routing

Model assignments live in `src/core/llm/router.py` (TASK_MODEL_MAP) and `src/agents/config.py` (per-agent default_model). Approved model IDs:

| Model | ID | Role |
|-------|-----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Analytics, reports, writing, email, onboarding |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Guardrails, intent fallback |
| GPT-5.2 | `gpt-5.2` | Chat, tasks, calendar, life, booking agents |
| Gemini 3.1 Flash Lite | `gemini-3.1-flash-lite-preview` | Intent detection (primary), OCR, research, summarization |
| Gemini 3 Pro | `gemini-3-pro-preview` | Deep reasoning, complex analysis |

Never use dated suffixes (e.g., `claude-haiku-4-5-20251001`) or old model IDs (`gpt-4o`, `gemini-2.0-flash`).

### Agents (13)

| Agent | Model | Skills |
|-------|-------|--------|
| receipt | gemini-3.1-flash-lite-preview | scan_receipt, scan_document |
| analytics | claude-sonnet-4-6 | query_stats, complex_query, query_report |
| chat | gpt-5.2 | add_expense, add_income, correct_category, undo_last, set_budget, mark_paid, add_recurring, delete_data |
| onboarding | claude-sonnet-4-6 | onboarding, general_chat |
| tasks | gpt-5.2 | create_task, list_tasks, set_reminder, complete_task, shopping_list_add, shopping_list_view, shopping_list_remove, shopping_list_clear |
| research | gemini-3.1-flash-lite-preview | quick_answer, web_search, compare_options, maps_search, youtube_search, price_check, web_action, browser_action |
| writing | claude-sonnet-4-6 | draft_message, translate_text, write_post, proofread, generate_image, generate_card, generate_program, modify_program |
| email | claude-sonnet-4-6 | read_inbox, send_email, draft_reply, follow_up_email, summarize_thread |
| calendar | gpt-5.2 | list_events, create_event, find_free_slots, reschedule_event, morning_brief |
| life | gpt-5.2 | quick_capture, track_food, track_drink, mood_checkin, day_plan, day_reflection, life_search, set_comm_mode, evening_recap, price_alert, news_monitor |
| booking | gpt-5.2 | create_booking, list_bookings, cancel_booking, reschedule_booking, add_contact, list_contacts, find_contact, send_to_client, receptionist |
| document | claude-sonnet-4-6 | scan_document, convert_document, list_documents, search_documents, extract_table, generate_invoice_pdf, fill_template, fill_pdf_form, analyze_document, merge_documents, pdf_operations, generate_spreadsheet, compare_documents, summarize_document, generate_document, generate_presentation |
| finance_specialist | claude-sonnet-4-6 | financial_summary, generate_invoice, tax_estimate, cash_flow_forecast |

### Context Assembly & Memory Layers

`src/core/memory/context.py` — `QUERY_CONTEXT_MAP` defines per-intent which layers to load. Total budget: 200K * 0.75 = 150K tokens. Progressive context disclosure skips heavy layers for simple inputs like "100 кофе" or "да".

**Memory layers (loaded in cache-optimal order):**

| # | Layer | Source | Tokens | Cacheable |
|---|-------|--------|--------|-----------|
| 0 | Core Identity | `src/core/identity.py` → `user_profiles.core_identity` JSONB | ~3K | Yes |
| 1 | System Prompt | Agent config + specialist knowledge | ~20K | Yes |
| 2 | Procedures | `src/core/memory/procedural.py` → Mem0 `procedures` domain | ~3-5K | Yes |
| 3 | Session Buffer | `src/core/memory/session_buffer.py` → Redis `session_facts:{uid}` | ~1K | No |
| 4 | Mem0 Memories | `src/core/memory/mem0_client.py` → domain-scoped search | ~8-30K | No |
| 5 | SQL Analytics | Per-intent stats from database | ~30K | No |
| 6 | Session Summary | `src/core/memory/summarization.py` | ~2K | No |
| 7 | Episodic | `src/core/memory/episodic.py` → past episodes for generative skills | ~2K | No |
| 8 | Observational | `src/core/memory/observational.py` → behavioral patterns | ~2K | No |
| 9 | Graph | `src/core/memory/graph_memory.py` → entity relationships | ~1K | No |
| 10 | History | Sliding window from Redis | varies | No |

**Overflow priority** (drop order): old history → non-core Mem0 → summary → SQL (compress to 2K first) → core Mem0 → NEVER: system prompt + identity + user message.

**Mem0 Domain Segmentation** (`src/core/memory/mem0_domains.py`): 11 namespaces with hard isolation via scoped user_id `{user_id}:{domain}`. Domains: core, finance, life, contacts, documents, content, tasks, calendar, research, episodes, procedures.

### Database

SQLAlchemy 2.0 async with `asyncpg`. 35+ tables across 28 Alembic migrations. Models in `src/core/models/`. Sessions via `async_session()` or `rls_session(family_id)` from `src/core/db.py`. Row-Level Security via PostgreSQL `set_config('app.current_family_id', ...)`. All tables have `family_id` FK for multi-tenant isolation. UUID primary keys. Run `alembic heads` before creating migrations to check for multiple heads.

### LangGraph Orchestrators

- **EmailOrchestrator** (`src/orchestrators/email/`): `planner → reader → writer → reviewer → approval → END` with revision loop (max 2 revisions) and HITL interrupt. Nodes decorated with `@with_retry` + `@with_timeout`. DLQ on fatal failure.
- **BriefOrchestrator** (`src/orchestrators/brief/`): Parallel fan-out collecting calendar, tasks, finance, email, overdue payments → Claude Sonnet synthesizer. Node caching (60s TTL). All collectors: `@with_retry(1)` + `@with_timeout(15)`.
- **BookingOrchestrator** (`src/orchestrators/booking/`): LangGraph FSM for multi-step hotel booking with interrupt-based user confirmation. Gated by `ff_langgraph_booking`. Search/execute nodes: `@with_timeout(60)`.
- **ApprovalOrchestrator** (`src/orchestrators/approval/`): 2-node graph (`ask_approval → execute_action → END`) with `interrupt()`/`resume()`.

**Resilience** (`src/orchestrators/resilience.py`): `@with_timeout(seconds)`, `@with_retry(max_retries, backoff_base)` decorators. `save_to_dlq()` persists failed state to `orchestrator_dlq` table. State sanitized via `_sanitize_state()` before JSONB storage.

**Recovery** (`src/orchestrators/recovery.py`): `recover_pending_graphs()` scans checkpointer at startup for interrupted HITL threads (24h window). `get_dlq_entries()` for monitoring. Integrated into `api/main.py` lifespan.

### Infrastructure Modules

- **Rate Limiter** (`src/core/rate_limiter.py`): Tiered limits — default 30/min, llm_heavy 10/min, browser 3/5min, document_gen 5/5min, image_gen 5/5min. Redis INCR+EXPIRE. `INTENT_TIER_MAP` maps expensive intents to tiers.
- **Circuit Breaker** (`src/core/circuit_breaker.py`): CLOSED→OPEN→HALF_OPEN pattern. Named instances for Mem0, Anthropic/OpenAI/Google, Redis. Prevents cascading failures.
- **Prompt Registry** (`src/core/prompt_registry.py`): Loads all `prompts.yaml`, SHA-256 versioning. `get(skill_name)`, `get_version(skill_name)`.
- **Health** (`api/main.py`): `/health` (basic) + `/health/detailed` (authenticated, includes circuit breaker states). Checkpointer health via `src/orchestrators/checkpointer.py:is_healthy()`.

### AI Data Tools (LLM Function Calling)

`src/tools/data_tools.py` — 5 universal database tools (`query_data`, `create_record`, `update_record`, `delete_record`, `aggregate_data`). LLM decides which tools to call via multi-provider function calling (`src/core/llm/clients.py:generate_text_with_tools()`). Enabled on 6 agents: analytics, chat, tasks, life, booking, finance_specialist (`data_tools_enabled=True`). Security: family_id injection, table whitelist (13 tables), column validation, confirm-before-delete for important tables.

**Progressive Tool Loading** (`src/tools/data_tool_schemas.py`): `get_schemas_for_domain(agent_name)` returns only the tables relevant to an agent's domain (~70% token reduction). `DOMAIN_TABLES` maps 6 domains to table groups. `_ADJACENT_DOMAINS` enables cross-domain queries (e.g., tasks agent sees shopping tables). `_AGENT_DOMAIN_MAP` routes agent names to primary domains. Unknown agents fall back to full schemas.

### Background Tasks

Taskiq + Redis (`src/core/tasks/broker.py`). 9 task modules: `memory_tasks`, `notification_tasks`, `life_tasks`, `reminder_tasks`, `profile_tasks`, `proactivity_tasks`, `booking_tasks`, `document_tasks`, `crossdomain_tasks`. Cron tasks include: daily budget alerts, weekly pattern analysis, recurring payment processing, life digests, morning/evening reminders, task reminders (every minute), proactive triggers (every 10 min), booking reminders, no-show detection, nightly profile learning, document cleanup (daily 03:00), recurring document generation (daily 09:00), weekly cross-domain insights, weekly procedural memory update. Skills can return `background_tasks` in SkillResult for async Mem0 updates, merchant mapping, budget checks.

### Multi-Channel Gateways

Telegram is primary. Slack (`src/gateway/slack_gw.py`), WhatsApp (`src/gateway/whatsapp_gw.py`), and SMS/Twilio (`src/gateway/sms_gw.py`) are implemented and activate when env vars are set. Channel linking via `channel_links` table maps external IDs to internal users.

### Dual-Mode Research Skills

`maps_search` and `youtube_search` use **Gemini Google Search Grounding** as default (quick mode). Direct REST APIs (Google Maps Platform, YouTube Data API v3) activate only when `detail_mode=True` AND the respective API key is configured. YouTube also supports direct URL analysis — sending a YouTube link triggers Gemini to analyze that specific video.

### Supervisor Routing & Skill Catalog

`src/core/supervisor.py` — Hierarchical 2-level routing for scaling to 200+ skills. Level 1: keyword-based domain resolution (zero LLM cost). Level 2: scoped intent detection with only the domain's intents. Gated by `ff_supervisor_routing`. `src/core/skill_catalog.py` loads `config/skill_catalog.yaml` — 13 domains, 93 skills, with trigger keywords per domain. `detect_intent_v2()` in `src/core/intent.py` uses this for progressive skill loading (95% reduction in intent prompt size).

### Specialist Config Engine

`src/core/specialist.py` — YAML-driven business-specific configuration that adapts the booking agent into a specialized receptionist. Pydantic models: `SpecialistConfig`, `SpecialistService`, `SpecialistStaff`, `WorkingHours`. Optional `specialist:` section in `config/profiles/*.yaml` defines services, staff, working hours, greetings, FAQ, capabilities, and extra system prompt. `ProfileConfig.specialist` loaded by `ProfileLoader`. `AgentRouter._add_specialist_knowledge()` injects specialist knowledge into system prompts. Currently configured: `manicure.yaml`, `flowers.yaml`, `construction.yaml`. Profiles without `specialist:` section work unchanged.

### Document Agent

13th agent (`src/agents/config.py`), model `claude-sonnet-4-6`, 16 skills spanning 4 phases. Skills: scan_document, convert_document (batch via Redis queue + zip), list_documents, search_documents (pg_trgm GIN indexes + pgvector hybrid via `src/core/memory/document_vectors.py`), extract_table, generate_invoice_pdf (WeasyPrint), fill_template (docxtpl/openpyxl + template library: save/list/delete), fill_pdf_form (pypdf), analyze_document (dual text/vision via Gemini), merge_documents (Redis multi-file queue), pdf_operations (split/rotate/encrypt/decrypt via pypdf), generate_spreadsheet (E2B + openpyxl fallback), compare_documents (text extraction + Claude diff), summarize_document, generate_document (contracts/NDAs via Claude + WeasyPrint), generate_presentation (E2B + python-pptx fallback). Document versioning via `version` + `parent_document_id` columns. Feature flag `ff_extended_context` gates 1M token context for heavy multi-doc analysis. Cron tasks: `cleanup_old_documents` (daily 03:00, 90-day retention, preserves templates/invoices), `generate_recurring_documents` (daily 09:00, metadata_extra scheduling).

### Browser Tools

`src/tools/browser.py` (Browser-Use + Playwright fallback), `src/tools/browser_booking.py` (Playwright booking with saved card detection), `src/tools/browser_login.py` (Telegram login flow with Fernet-encrypted cookies in Supabase), `src/tools/browser_service.py` (service layer). The `browser_action` skill uses authenticated Playwright sessions; `web_action` uses headless browsing for simpler tasks.

### Callback Handler (Inline Buttons)

`src/core/router.py:_handle_callback()` — central dispatcher for ALL inline button presses. Callbacks use colon-delimited format: `action:subaction:param`. Key prefixes: `confirm`/`cancel` (transaction), `onboard:` (language/account), `stats:` (weekly/trend), `correct:` (category), `life_search:` (period), `clarify:` (disambiguation), `confirm_action:`/`cancel_action:` (pending actions from Redis), `graph_resume:` (LangGraph HITL), `hotel_*` (booking flow), `receipt_confirm:` (receipt parsing). For complex data, store in Redis with 8-char ID and pass the ID in the callback string.

## Adding a New Skill

1. Create `src/skills/<name>/__init__.py` (empty) and `src/skills/<name>/handler.py`
2. Handler exports a class with `name`, `intents`, `model`, `execute()`, `get_system_prompt()` + module-level `skill = ClassName()`
3. Register in `src/skills/__init__.py`: import and `registry.register(skill)`
4. Add intent to `INTENT_DETECTION_PROMPT` in `src/core/intent.py` (with priority rules)
5. Add extracted fields to `IntentData` in `src/core/schemas/intent.py` if needed
6. Add `QUERY_CONTEXT_MAP` entry in `src/core/memory/context.py`
7. Assign to an agent's `skills` list in `src/agents/config.py`
8. Add skill to domain in `config/skill_catalog.yaml` (triggers + skills list)
9. Add intent→domain mapping in `src/core/domains.py` (`INTENT_DOMAIN_MAP`)
10. Update tests in `tests/test_skills/test_registry.py` (count + intents list)
11. Create `tests/test_skills/test_<name>.py` with mocked external I/O

## Critical Patterns

### IntentData → Handler field flow
`detect_intent()` → `IntentDetectionResult.data` → `model_dump()` → dict passed to `handler.execute()`. Handler `intent_data.get()` keys **MUST** match `IntentData` field names exactly.

### Alembic + PostgreSQL enums
Never use `sa.Enum(create_type=False)` in `op.create_table` — SQLAlchemy ignores it. PostgreSQL does NOT support `CREATE TYPE IF NOT EXISTS`. Use `DO $$ BEGIN CREATE TYPE ... AS ENUM (...); EXCEPTION WHEN duplicate_object THEN NULL; END $$`. Tables: use `CREATE TABLE IF NOT EXISTS`. Watch for multiple heads after branch merges — use `down_revision = ("rev_a", "rev_b")` tuple for merge points. Always run `alembic heads` before creating a new migration.

### Intent prompt `.format()` escaping
`INTENT_DETECTION_PROMPT` in `src/core/intent.py` uses `.format(today=...)`. Any literal curly braces in the prompt (e.g., JSON examples like `{description, amount}`) MUST be doubled `{{description, amount}}` to avoid KeyError.

### `_SKILL_ONLY_INTENTS` — bypass data_tools
Agents with `data_tools_enabled=True` (analytics, chat, tasks, life, booking, finance_specialist) route through LLM function calling by default. Intents listed in `_SKILL_ONLY_INTENTS` (`src/agents/base.py`) skip this and use their dedicated skill handler instead. Currently: `set_reminder`, `query_stats`, `query_report`. Add intents here when the dedicated handler has logic (period resolution, charts, PDF generation) that the generic data_tools path cannot replicate.

### Lazy imports in orchestrator modules
`src/orchestrators/resilience.py` and `src/orchestrators/recovery.py` use lazy imports inside functions (e.g., `from src.core.db import async_session` inside `save_to_dlq()`). When writing tests, patch at the **source** module (`src.core.db.async_session`), not at the consumer module.

### Gemini Google Search Grounding pattern
```python
from google.genai import types
from src.core.llm.clients import google_client

client = google_client()
response = await client.aio.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    ),
)
```

## Testing Patterns

- `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- Fixtures in `tests/conftest.py`: `sample_context`, `member_context`, `text_message`, `photo_message`, `callback_message`, `skill_registry`, `mock_gateway`, `profile_loader`
- Mock external calls with `unittest.mock.patch` + `AsyncMock`:
  ```python
  with patch("src.skills.<name>.handler.save_life_event", new_callable=AsyncMock) as mock:
      result = await skill.execute(message, context, intent_data)
  ```
- Tests never hit real DBs or LLM APIs — all external I/O is mocked
- `tests/conftest.py` sets env vars: `APP_ENV=testing`, `DATABASE_URL=postgresql+asyncpg://test:test@localhost/test`
- Known issue: `test_registry.py` hangs under full suite due to heavy imports (nemoguardrails/langgraph) via `create_registry()`. Individual test files run fine.

## Product & PM Workflow

This project is an **AI Life Assistant** ($49/month). Implementation plan: `IMPLEMENTATION_PLAN.md`.

### Before implementing any new module or phase:

1. **Read PM skills** in `skills/pm/` — especially `PM_SKILL.md` and `PRD_TEMPLATE.md`
2. **Write a PRD** to `docs/prds/<module-name>.md` using the template
3. **Include Maria & David scenarios** (Brooklyn mom + Queens plumber — see `PM_SKILL.md`)
4. **Self-score** using the rubric in `PRD_TEMPLATE.md` — must be **25+/30** before coding
5. **State star rating** using `skills/pm/11_STAR_EXPERIENCE.md` — MVP = 6 stars
6. **Only then** start implementation

### Bot message quality:

- All bot-facing text (system prompts, responses) must follow `skills/pm/LANGUAGE_VOICE.md`
- Smart capable friend tone — not corporate, not chirpy
- Lead with the answer, use contractions, max 3 sentences for confirmations

## Plans & Docs

- `docs/plans/2026-02-25-comprehensive-integration-analysis.md` — Master integration plan: LangGraph, Deep Agents, LangSmith, 40+ specialists, scaling roadmap
- `docs/plans/2026-02-25-langgraph-langchain-integration-audit.md` — LangGraph/LangChain audit (Codex): 5 priorities (P1 Booking FSM, P2 HITL, P3 Brief, P4 Email, P5 New domains)
- `docs/plans/2026-02-25-architecture-audit-vnext-language-timezone-reminders.md` — Locale/timezone/reminder vNext (Phase 0-1 done, Phase 2 partial)
- `docs/plans/2026-02-24-multi-agent-orchestrator-design.md` — Multi-agent dev workflow (Claude Code + Codex/Gemini in worktrees)

## Conventions

- Bot language: English (primary) → Spanish (second) → user's preferred language
- Telegram HTML formatting (not Markdown) — `<b>`, `<i>`, `<code>`
- Langfuse observability via `@observe(name="...")` decorator from `src/core/observability.py`
- Business profiles in `config/profiles/*.yaml` define categories, metrics, reports, and optional `specialist:` config (services, staff, hours, FAQ) per business type
- Communication modes for life-tracking skills: `silent` (no response), `receipt` (one-line confirmation, default), `coaching` (confirmation + AI insight)
- Confirmation flow: dangerous actions (delete, send email, create event) store pending action in Redis + show inline buttons → callback handler executes or cancels
- Google OAuth required for email/calendar skills — use `require_google_or_prompt` helper

## Deployment

- **Railway**: `railway up -d` from project root. Entrypoint: `scripts/entrypoint.sh` → `alembic upgrade head` → `uvicorn`
- **Docker**: Multi-stage Dockerfile (python:3.12-slim), WeasyPrint deps, healthcheck on `/health`
- **CI/CD**: `.github/workflows/ci.yml` — lint → test (with Redis service) → docker build → Railway deploy (requires `RAILWAY_TOKEN` secret AND `vars.RAILWAY_DEPLOY=true` repository variable)
- **Worker process**: Separate Railway service with `RAILWAY_PROCESS_TYPE=worker` for Taskiq worker + scheduler
