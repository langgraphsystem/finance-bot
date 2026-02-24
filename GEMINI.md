# Instructions for Gemini

You are working on a Python 3.12+ AI Life Assistant project (Telegram bot).

## Rules
- NEVER modify files outside your task scope
- NEVER delete files unless explicitly asked
- NEVER run destructive commands (drop tables, rm -rf, git push --force)
- Use sandbox mode for all shell commands
- All tests must pass before considering your work done
- Use existing patterns from the codebase — read similar files first
- Commit your changes with a descriptive message when done

## Code style
- Line-length: 100
- Ruff rules: E, F, I, N, W, UP
- pytest-asyncio with asyncio_mode="auto" — no @pytest.mark.asyncio needed
- Mock ALL external I/O in tests (DB, LLM APIs, Redis) using unittest.mock.patch + AsyncMock
- Telegram HTML formatting in bot responses: <b>, <i>, <code> — NOT Markdown

## Project structure
- Skills: src/skills/<name>/handler.py — each exports `skill = ClassName()`
- Models: src/core/models/ — SQLAlchemy 2.0 async
- Tests: tests/test_skills/test_<name>.py
- Agent configs: src/agents/config.py
- Intent detection: src/core/intent.py
- Test fixtures: tests/conftest.py (sample_context, text_message, photo_message)

## Model IDs (use ONLY these)
- claude-sonnet-4-6, claude-haiku-4-5, gpt-5.2
- gemini-3-flash-preview, gemini-3-pro-preview
- NEVER use dated suffixes like claude-haiku-4-5-20251001

## Test pattern
```python
from unittest.mock import AsyncMock, patch
from src.skills.<name>.handler import skill

async def test_something(sample_context, text_message):
    with patch("src.skills.<name>.handler.<external_call>", new_callable=AsyncMock) as mock:
        mock.return_value = ...
        result = await skill.execute(text_message, sample_context, {"key": "value"})
        assert result.response_text
        mock.assert_called_once()
```
