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
```

**Ruff config**: Python 3.12+, line-length 100, rules: E, F, I, N, W, UP.

## Architecture

### Message Flow

Telegram (aiogram v3) → `api/main.py` webhook → `src/core/router.py` builds `SessionContext` → `src/core/intent.py` detects intent (Gemini Flash primary, Claude Haiku fallback) → `src/agents/base.py:AgentRouter` maps intent → `AgentConfig` → `src/core/memory/context.py` assembles multi-layer context with token budget → skill's `execute()` runs → `SkillResult` returned → formatted and sent via `src/gateway/telegram.py`.

### Key Abstractions

- **SessionContext** (`src/core/context.py`): Immutable per-request context with user_id, family_id, role, categories, merchant_mappings. Enforces multi-tenant isolation.
- **AgentConfig** (`src/agents/config.py`): 5 agents (receipt, analytics, chat, onboarding, life), each with system prompt, model, skill list, and `context_config` dict (`mem`/`hist`/`sql`/`sum` — which memory layers to load).
- **BaseSkill** protocol (`src/skills/base.py`): `name`, `intents[]`, `model`, `execute(message, context, intent_data) → SkillResult`, `get_system_prompt(context)`.
- **SkillResult** (`src/skills/base.py`): `response_text` + optional `buttons`, `document`, `chart_url`, `background_tasks`.
- **SkillRegistry** (`src/skills/__init__.py`): Maps intent strings to skill instances. `get(intent) → skill`.

### Model Routing

Model assignments live in `src/core/llm/router.py` (TASK_MODEL_MAP) and `src/agents/config.py` (per-agent default_model). Approved model IDs:

| Model | ID | Role |
|-------|-----|------|
| Claude Opus 4.6 | `claude-opus-4-6` | Complex tasks |
| Claude Sonnet 4.5 | `claude-sonnet-4-5` | Analytics, reports |
| Claude Haiku 4.5 | `claude-haiku-4-5` | Chat, skills, fallback |
| GPT-5.2 | `gpt-5.2` | Fallback |
| Gemini 3 Flash | `gemini-3-flash-preview` | Intent, OCR, summarization |
| Gemini 3 Pro | `gemini-3-pro-preview` | Deep reasoning |

Never use dated suffixes (e.g., `claude-haiku-4-5-20251001`) or old model IDs (`gpt-4o`, `gemini-2.0-flash`).

### Context Assembly & Token Budget

`src/core/memory/context.py` — `QUERY_CONTEXT_MAP` defines per-intent which layers to load (Mem0 memories, SQL stats, sliding window history, session summary). Total budget: 200K * 0.75 = 150K tokens. Overflow priority drops old messages first, then summary, then SQL, then Mem0. System prompt and current message are never dropped. Uses Lost-in-the-Middle positioning.

### Database

SQLAlchemy 2.0 async with `asyncpg`. Models in `src/core/models/`. Sessions via `async_session()` or `rls_session(family_id)` from `src/core/db.py`. Row-Level Security via PostgreSQL `set_config('app.current_family_id', ...)`. All tables have `family_id` FK for multi-tenant isolation. UUID primary keys. Alembic migrations in `alembic/versions/`.

### Background Tasks

Taskiq + Redis (`src/core/tasks/broker.py`). Cron tasks in `src/core/tasks/notification_tasks.py` and `src/core/tasks/life_tasks.py`. Skills can return `background_tasks` in SkillResult for async Mem0 updates, merchant mapping, budget checks.

## Adding a New Skill

1. Create `src/skills/<name>/__init__.py` (empty) and `src/skills/<name>/handler.py`
2. Handler exports a class with `name`, `intents`, `model`, `execute()`, `get_system_prompt()` + module-level `skill = ClassName()`
3. Register in `src/skills/__init__.py`: import and `registry.register(skill)`
4. Add intent to `INTENT_DETECTION_PROMPT` in `src/core/intent.py`
5. Add extracted fields to `IntentData` in `src/core/schemas/intent.py` if needed
6. Add `QUERY_CONTEXT_MAP` entry in `src/core/memory/context.py`
7. Assign to an agent's `skills` list in `src/agents/config.py`
8. Update tests in `tests/test_skills/test_registry.py` (count + intents list)

## Testing Patterns

- `pytest-asyncio` with `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio` in most cases
- Fixtures in `tests/conftest.py`: `sample_context`, `text_message`, `photo_message`, `skill_registry`
- Mock external calls with `unittest.mock.patch` + `AsyncMock`:
  ```python
  with patch("src.skills.<name>.handler.save_life_event", new_callable=AsyncMock) as mock:
      result = await skill.execute(message, context, intent_data)
  ```
- Tests never hit real DBs or LLM APIs — all external I/O is mocked
- `tests/conftest.py` sets env vars: `APP_ENV=testing`, `DATABASE_URL=postgresql+asyncpg://test:test@localhost/test`

## Conventions

- All user-facing text is in Russian
- Telegram HTML formatting (not Markdown) — `<b>`, `<i>`, `<code>`
- Langfuse observability via `@observe(name="...")` decorator from `src/core/observability.py`
- Business profiles in `config/profiles/*.yaml` define categories, metrics, reports per business type
- Communication modes for life-tracking skills: `silent` (no response), `receipt` (one-line confirmation, default), `coaching` (confirmation + AI insight)
