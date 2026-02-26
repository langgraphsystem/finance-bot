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
TASK_MODULES="src.core.tasks.memory_tasks src.core.tasks.notification_tasks src.core.tasks.life_tasks src.core.tasks.reminder_tasks src.core.tasks.profile_tasks src.core.tasks.proactivity_tasks src.core.tasks.booking_tasks"
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
  → src/core/guardrails.py input safety check (Claude Haiku)
  → src/core/intent.py detects intent (Gemini Pro primary, Claude Haiku fallback)
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
- **AgentConfig** (`src/agents/config.py`): 12 agents, each with system prompt, model, skill list, and `context_config` dict (`mem`/`hist`/`sql`/`sum` — which memory layers to load).
- **BaseSkill** protocol (`src/skills/base.py`): `name`, `intents[]`, `model`, `execute(message, context, intent_data) → SkillResult`, `get_system_prompt(context)`.
- **SkillResult** (`src/skills/base.py`): `response_text` + optional `buttons`, `document`, `document_name`, `photo_url`, `photo_bytes`, `chart_url`, `reply_keyboard`, `background_tasks`.
- **SkillRegistry** (`src/skills/__init__.py`): Maps intent strings to skill instances. `get(intent) → skill`. Currently 74 skills registered.
- **DomainRouter** (`src/core/domain_router.py`): Routes intents to LangGraph orchestrators or AgentRouter. Orchestrators registered: email, brief, booking (if `ff_langgraph_booking`). Approval orchestrator invoked directly via `start_approval()`.

### Model Routing

Model assignments live in `src/core/llm/router.py` (TASK_MODEL_MAP) and `src/agents/config.py` (per-agent default_model). Approved model IDs:

| Model | ID | Role |
|-------|-----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Analytics, reports, writing, email, onboarding |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Guardrails, intent fallback |
| GPT-5.2 | `gpt-5.2` | Chat, tasks, calendar, life, booking agents |
| Gemini 3 Flash | `gemini-3-flash-preview` | OCR, research, summarization |
| Gemini 3 Pro | `gemini-3-pro-preview` | Intent detection (primary), deep reasoning |

Never use dated suffixes (e.g., `claude-haiku-4-5-20251001`) or old model IDs (`gpt-4o`, `gemini-2.0-flash`).

### Agents (12)

| Agent | Model | Skills |
|-------|-------|--------|
| receipt | gemini-3-flash-preview | scan_receipt, scan_document |
| analytics | claude-sonnet-4-6 | query_stats, complex_query, query_report |
| chat | gpt-5.2 | add_expense, add_income, correct_category, undo_last, set_budget, mark_paid, add_recurring, delete_data |
| onboarding | claude-sonnet-4-6 | onboarding, general_chat |
| tasks | gpt-5.2 | create_task, list_tasks, set_reminder, complete_task, shopping_list_add, shopping_list_view, shopping_list_remove, shopping_list_clear |
| research | gemini-3-flash-preview | quick_answer, web_search, compare_options, maps_search, youtube_search, price_check, web_action, browser_action |
| writing | claude-sonnet-4-6 | draft_message, translate_text, write_post, proofread, generate_image, generate_card, generate_program, modify_program, convert_document |
| email | claude-sonnet-4-6 | read_inbox, send_email, draft_reply, follow_up_email, summarize_thread |
| calendar | gpt-5.2 | list_events, create_event, find_free_slots, reschedule_event, morning_brief |
| life | gpt-5.2 | quick_capture, track_food, track_drink, mood_checkin, day_plan, day_reflection, life_search, set_comm_mode, evening_recap, price_alert, news_monitor |
| booking | gpt-5.2 | create_booking, list_bookings, cancel_booking, reschedule_booking, add_contact, list_contacts, find_contact, send_to_client, receptionist |
| finance_specialist | claude-sonnet-4-6 | financial_summary, generate_invoice, tax_estimate, cash_flow_forecast |

### Context Assembly & Token Budget

`src/core/memory/context.py` — `QUERY_CONTEXT_MAP` defines per-intent which layers to load (Mem0 memories, SQL stats, sliding window history, session summary). Total budget: 200K * 0.75 = 150K tokens. Overflow priority drops old messages first, then summary, then SQL, then Mem0. System prompt and current message are never dropped. Uses Lost-in-the-Middle positioning. Progressive context disclosure skips heavy layers for simple inputs like "100 кофе" or "да".

### Database

SQLAlchemy 2.0 async with `asyncpg`. 30 tables across 13 Alembic migrations. Models in `src/core/models/`. Sessions via `async_session()` or `rls_session(family_id)` from `src/core/db.py`. Row-Level Security via PostgreSQL `set_config('app.current_family_id', ...)`. All tables have `family_id` FK for multi-tenant isolation. UUID primary keys. Run `alembic heads` before creating migrations to check for multiple heads.

### LangGraph Orchestrators

- **EmailOrchestrator** (`src/orchestrators/email/`): `planner → reader → writer → reviewer → approval → END` with revision loop (max 2 revisions) and HITL interrupt. For `send_email` and `draft_reply`.
- **BriefOrchestrator** (`src/orchestrators/brief/`): Parallel fan-out (Deferred Nodes) collecting calendar, tasks, finance, email, overdue payments → Claude Sonnet synthesizer. Node caching (60s TTL). For `morning_brief` and `evening_recap`. Business-type aware via plugin_loader.
- **BookingOrchestrator** (`src/orchestrators/booking/`): LangGraph FSM for multi-step hotel booking with interrupt-based user confirmation. Gated by `ff_langgraph_booking`.
- **ApprovalOrchestrator** (`src/orchestrators/approval/`): 2-node graph (`ask_approval → execute_action → END`) with `interrupt()`/`resume()`. Replaces Redis pending_actions for dangerous actions (send_email, create_event, delete).

### Background Tasks

Taskiq + Redis (`src/core/tasks/broker.py`). 11 cron tasks across 7 task modules: daily budget alerts, weekly pattern analysis, recurring payment processing, life digests, morning/evening reminders, task reminders (every minute), proactive triggers (every 10 min), booking reminders, no-show detection, nightly profile learning. Skills can return `background_tasks` in SkillResult for async Mem0 updates, merchant mapping, budget checks.

### Multi-Channel Gateways

Telegram is primary. Slack (`src/gateway/slack_gw.py`), WhatsApp (`src/gateway/whatsapp_gw.py`), and SMS/Twilio (`src/gateway/sms_gw.py`) are implemented and activate when env vars are set. Channel linking via `channel_links` table maps external IDs to internal users.

### Dual-Mode Research Skills

`maps_search` and `youtube_search` use **Gemini Google Search Grounding** as default (quick mode). Direct REST APIs (Google Maps Platform, YouTube Data API v3) activate only when `detail_mode=True` AND the respective API key is configured. YouTube also supports direct URL analysis — sending a YouTube link triggers Gemini to analyze that specific video.

### AI Data Tools (LLM Function Calling)

`src/tools/data_tools.py` — 5 universal database tools (`query_data`, `create_record`, `update_record`, `delete_record`, `aggregate_data`). LLM decides which tools to call via multi-provider function calling (`src/core/llm/clients.py:generate_text_with_tools()`). Enabled on 5 agents: analytics, chat, tasks, life, booking (`data_tools_enabled=True` in AgentConfig). Security: family_id injection, table whitelist (11 tables), column validation, confirm-before-delete for important tables. Schemas in `src/tools/data_tool_schemas.py`, executor in `src/tools/tool_executor.py`.

### Supervisor Routing & Skill Catalog

`src/core/supervisor.py` — Hierarchical 2-level routing for scaling to 200+ skills. Level 1: keyword-based domain resolution (zero LLM cost). Level 2: scoped intent detection with only the domain's intents. Gated by `ff_supervisor_routing`. `src/core/skill_catalog.py` loads `config/skill_catalog.yaml` — 12 domains, 74 skills, with trigger keywords per domain. `detect_intent_v2()` in `src/core/intent.py` uses this for progressive skill loading (95% reduction in intent prompt size).

### Specialist Config Engine

`src/core/specialist.py` — YAML-driven business-specific configuration that adapts the booking agent into a specialized receptionist. Pydantic models: `SpecialistConfig`, `SpecialistService`, `SpecialistStaff`, `WorkingHours`. Optional `specialist:` section in `config/profiles/*.yaml` defines services, staff, working hours, greetings, FAQ, capabilities, and extra system prompt. `ProfileConfig.specialist` loaded by `ProfileLoader`. `AgentRouter._add_specialist_knowledge()` injects specialist knowledge into system prompts. Currently configured: `manicure.yaml`, `flowers.yaml`, `construction.yaml`. Profiles without `specialist:` section work unchanged.

### Browser Tools

`src/tools/browser.py` (Browser-Use + Playwright fallback), `src/tools/browser_booking.py` (Playwright booking with saved card detection), `src/tools/browser_login.py` (Telegram login flow with Fernet-encrypted cookies in Supabase), `src/tools/browser_service.py` (service layer). The `browser_action` skill uses authenticated Playwright sessions; `web_action` uses headless browsing for simpler tasks.

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
Never use `sa.Enum(create_type=False)` in `op.create_table` — SQLAlchemy ignores it. Use raw SQL: `CREATE TYPE IF NOT EXISTS` + `CREATE TABLE IF NOT EXISTS`. Watch for multiple heads after branch merges — use `down_revision = ("rev_a", "rev_b")` tuple for merge points. Always run `alembic heads` before creating a new migration.

### Gemini Google Search Grounding pattern
```python
from google.genai import types
from src.core.llm.clients import google_client

client = google_client()
response = await client.aio.models.generate_content(
    model="gemini-3-flash-preview",
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
