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

# Task queue worker
python -m taskiq worker src.core.tasks.broker:broker

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

- **SessionContext** (`src/core/context.py`): Immutable per-request context with user_id, family_id, role, categories, merchant_mappings. Enforces multi-tenant isolation.
- **AgentConfig** (`src/agents/config.py`): 11 agents, each with system prompt, model, skill list, and `context_config` dict (`mem`/`hist`/`sql`/`sum` — which memory layers to load).
- **BaseSkill** protocol (`src/skills/base.py`): `name`, `intents[]`, `model`, `execute(message, context, intent_data) → SkillResult`, `get_system_prompt(context)`.
- **SkillResult** (`src/skills/base.py`): `response_text` + optional `buttons`, `document`, `chart_url`, `background_tasks`.
- **SkillRegistry** (`src/skills/__init__.py`): Maps intent strings to skill instances. `get(intent) → skill`. Currently 61 skills registered.
- **DomainRouter** (`src/core/domain_router.py`): Routes intents to LangGraph orchestrators or AgentRouter. Orchestrators registered: email (send_email, draft_reply) and brief (morning_brief, evening_recap).

### Model Routing

Model assignments live in `src/core/llm/router.py` (TASK_MODEL_MAP) and `src/agents/config.py` (per-agent default_model). Approved model IDs:

| Model | ID | Role |
|-------|-----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | Analytics, reports, writing, email |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Chat, skills, fallback |
| GPT-5.2 | `gpt-5.2` | Fallback |
| Gemini 3 Flash | `gemini-3-flash-preview` | Intent, OCR, summarization, research |
| Gemini 3 Pro | `gemini-3-pro-preview` | Deep reasoning |

Never use dated suffixes (e.g., `claude-haiku-4-5-20251001`) or old model IDs (`gpt-4o`, `gemini-2.0-flash`).

### Agents (11)

| Agent | Model | Skills |
|-------|-------|--------|
| receipt | gemini-3-flash-preview | scan_receipt, scan_document |
| analytics | claude-sonnet-4-6 | query_stats, complex_query, query_report |
| chat | claude-haiku-4-5 | add_expense, add_income, correct_category, undo_last, set_budget, mark_paid, add_recurring |
| onboarding | claude-sonnet-4-6 | onboarding, general_chat |
| tasks | claude-haiku-4-5 | create_task, list_tasks, set_reminder, complete_task, shopping_list_* |
| research | gemini-3-flash-preview | quick_answer, web_search, compare_options, maps_search, youtube_search, price_check, web_action |
| writing | claude-sonnet-4-6 | draft_message, translate_text, write_post, proofread |
| email | claude-sonnet-4-6 | read_inbox, send_email, draft_reply, follow_up_email, summarize_thread |
| calendar | claude-haiku-4-5 | list_events, create_event, find_free_slots, reschedule_event, morning_brief |
| life | claude-haiku-4-5 | quick_capture, track_food, track_drink, mood_checkin, day_plan, day_reflection, life_search, set_comm_mode, evening_recap, price_alert, news_monitor |
| booking | claude-haiku-4-5 | create_booking, list_bookings, cancel_booking, reschedule_booking, add_contact, list_contacts, find_contact, send_to_client |

### Context Assembly & Token Budget

`src/core/memory/context.py` — `QUERY_CONTEXT_MAP` defines per-intent which layers to load (Mem0 memories, SQL stats, sliding window history, session summary). Total budget: 200K * 0.75 = 150K tokens. Overflow priority drops old messages first, then summary, then SQL, then Mem0. System prompt and current message are never dropped. Uses Lost-in-the-Middle positioning. Progressive context disclosure skips heavy layers for simple inputs like "100 кофе" or "да".

### Database

SQLAlchemy 2.0 async with `asyncpg`. 28 tables across 7 Alembic migrations. Models in `src/core/models/`. Sessions via `async_session()` or `rls_session(family_id)` from `src/core/db.py`. Row-Level Security via PostgreSQL `set_config('app.current_family_id', ...)`. All tables have `family_id` FK for multi-tenant isolation. UUID primary keys.

### LangGraph Orchestrators

- **EmailOrchestrator** (`src/orchestrators/email/`): `planner → reader → writer → reviewer → END` with revision loop (max 2 revisions). For `send_email` and `draft_reply`.
- **BriefOrchestrator** (`src/orchestrators/brief/`): Sequential fan-out collecting calendar, tasks, finance, email, overdue payments → Claude Sonnet synthesizer. For `morning_brief` and `evening_recap`. Business-type aware via plugin_loader.

### Background Tasks

Taskiq + Redis (`src/core/tasks/broker.py`). 11 cron tasks: daily budget alerts, weekly pattern analysis, recurring payment processing, life digests, morning/evening reminders, task reminders (every minute), proactive triggers (every 10 min), booking reminders, no-show detection, nightly profile learning. Skills can return `background_tasks` in SkillResult for async Mem0 updates, merchant mapping, budget checks.

### Multi-Channel Gateways

Telegram is primary. Slack (`src/gateway/slack_gw.py`), WhatsApp (`src/gateway/whatsapp_gw.py`), and SMS/Twilio (`src/gateway/sms_gw.py`) are implemented and activate when env vars are set. Channel linking via `channel_links` table maps external IDs to internal users.

### Dual-Mode Research Skills

`maps_search` and `youtube_search` use **Gemini Google Search Grounding** as default (quick mode). Direct REST APIs (Google Maps Platform, YouTube Data API v3) activate only when `detail_mode=True` AND the respective API key is configured. YouTube also supports direct URL analysis — sending a YouTube link triggers Gemini to analyze that specific video.

## Adding a New Skill

1. Create `src/skills/<name>/__init__.py` (empty) and `src/skills/<name>/handler.py`
2. Handler exports a class with `name`, `intents`, `model`, `execute()`, `get_system_prompt()` + module-level `skill = ClassName()`
3. Register in `src/skills/__init__.py`: import and `registry.register(skill)`
4. Add intent to `INTENT_DETECTION_PROMPT` in `src/core/intent.py` (with priority rules)
5. Add extracted fields to `IntentData` in `src/core/schemas/intent.py` if needed
6. Add `QUERY_CONTEXT_MAP` entry in `src/core/memory/context.py`
7. Assign to an agent's `skills` list in `src/agents/config.py`
8. Update tests in `tests/test_skills/test_registry.py` (count + intents list)
9. Create `tests/test_skills/test_<name>.py` with mocked external I/O

## Critical Patterns

### IntentData → Handler field flow
`detect_intent()` → `IntentDetectionResult.data` → `model_dump()` → dict passed to `handler.execute()`. Handler `intent_data.get()` keys **MUST** match `IntentData` field names exactly.

### Alembic + PostgreSQL enums
Never use `sa.Enum(create_type=False)` in `op.create_table` — SQLAlchemy ignores it. Use raw SQL: `CREATE TYPE IF NOT EXISTS` + `CREATE TABLE IF NOT EXISTS`. Watch for multiple heads after branch merges — use `down_revision = ("rev_a", "rev_b")` tuple for merge points.

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
- Fixtures in `tests/conftest.py`: `sample_context`, `text_message`, `photo_message`, `skill_registry`
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

## Conventions

- Bot language: English (primary) → Spanish (second) → user's preferred language
- Telegram HTML formatting (not Markdown) — `<b>`, `<i>`, `<code>`
- Langfuse observability via `@observe(name="...")` decorator from `src/core/observability.py`
- Business profiles in `config/profiles/*.yaml` define categories, metrics, reports per business type
- Communication modes for life-tracking skills: `silent` (no response), `receipt` (one-line confirmation, default), `coaching` (confirmation + AI insight)
- Confirmation flow: dangerous actions (delete, send email, create event) store pending action in Redis + show inline buttons → callback handler executes or cancels
- Google OAuth required for email/calendar skills — use `require_google_or_prompt` helper

## Deployment

- **Railway**: `railway up -d` from project root. Entrypoint: `scripts/entrypoint.sh` → `alembic upgrade head` → `uvicorn`
- **Docker**: Multi-stage Dockerfile (python:3.12-slim), WeasyPrint deps, healthcheck on `/health`
- **CI/CD**: `.github/workflows/ci.yml` — lint → test (with Redis service) → docker build → Railway deploy (requires `RAILWAY_TOKEN` secret)
- **Worker process**: Separate Railway service with `RAILWAY_PROCESS_TYPE=worker` for Taskiq cron tasks
