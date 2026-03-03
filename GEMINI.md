# Instructions for Gemini (v5.1)

You are working on a Python 3.12+ AI Life Assistant project (Telegram bot primary, plus Slack/WhatsApp/SMS).

## Rules
- NEVER modify files outside your task scope.
- NEVER delete files unless explicitly asked.
- NEVER run destructive commands (drop tables, rm -rf, git push --force).
- Use sandbox mode for all shell commands.
- All tests must pass before considering your work done.
- Use existing patterns from the codebase — read similar files first.
- Commit your changes with a descriptive message when done.
- Follow the 2-stage intent detection logic (Domain -> Intent).

## Code style
- Line-length: 100.
- Ruff rules: E, F, I, N, W, UP.
- pytest-asyncio with asyncio_mode="auto" — no `@pytest.mark.asyncio` needed.
- Mock ALL external I/O in tests (DB, LLM APIs, Redis, Google APIs, E2B) using `unittest.mock.patch` + `AsyncMock`.
- Telegram HTML formatting in bot responses: <b>, <i>, <code> — NOT Markdown.
- Use `aiogoogle` for all Google API interactions (Gmail, Calendar).
- Use `ConnectorRegistry` to access external service clients.
- **Localization:** ALWAYS use `context.timezone` for date/time and `context.language` for responses.

## Project structure
- **Domains:** Defined in `src/core/domains.py`.
- **Skills:** `src/skills/<name>/handler.py`. Each skill MUST have a `prompts.yaml`.
- **Orchestrators:** LangGraph-based in `src/orchestrators/<domain>/graph.py` (Email, Brief, Booking, Writing, Document).
- **Models:** SQLAlchemy 2.0 async in `src/core/models/`.
- **Gateways:** Multi-channel support in `src/gateway/` (Telegram, Slack, WhatsApp, SMS).
- **Intents:** 2-stage detection in `src/core/intent.py`.
- **Scheduled Intelligence:** Dynamic tasks via Taskiq in `src/proactivity/scheduled/`.
- **Document Agent:** Unified agent for OCR, conversion, generation, and analysis.

## Model IDs (use ONLY these)
- `claude-opus-4-6` (Complex tasks)
- `claude-sonnet-4-6` (Analytics, reports, writing, email, document analysis)
- `claude-haiku-4-5` (Chat, skills, calendar, tasks, fallback)
- `gpt-5.2` (Fallback, OCR, complex analysis)
- `gemini-3-flash-preview` (Intent detection, OCR, summarization, web search grounding)
- `gemini-3.1-pro-preview` (Deep reasoning)
- NEVER use dated suffixes like `claude-haiku-4-5-20251001`.

## Architectural Patterns
1. **DomainRouter:** Wraps `AgentRouter`. Routes to LangGraph orchestrators for complex flows or `AgentRouter` for simple CRUD.
2. **2-Stage Intent Detection:** Stage 1 (Domain) -> Stage 2 (Intent within domain). Activated when intents > 25.
3. **YAML Prompts:** Externalize system prompts to `src/skills/<name>/prompts.yaml`. Supports overrides via `config/plugins/`.
4. **Document Agent & E2B:**
   - Use `Claude Sonnet 4.6` + `E2B Sandbox` for generating Excel (`openpyxl`), PPTX (`python-pptx`), and complex PDF reports.
   - Use `pdfplumber` for table extraction from native PDFs.
   - Use `docxtpl` for Jinja2-based DOCX templates.
   - Use `Gemini 3 Flash` for fast OCR and image classification.
5. **Progressive Context:** Use complexity heuristics in `assemble_context` to reduce token usage for simple queries.
6. **Data Tools:** Agents with `data_tools_enabled=True` can query allowed tables (Document, Transactions, etc.) via LLM function calling.

## Test pattern
```python
from unittest.mock import AsyncMock, patch
from src.skills.<name>.handler import skill

async def test_something(sample_context, text_message):
    # Mock external calls, connectors, and sandbox
    with patch("src.core.connectors.google.GoogleConnector.get_client", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = AsyncMock()
        result = await skill.execute(text_message, sample_context, {"key": "value"})
        assert result.response_text
        # Assertions for your logic
```
