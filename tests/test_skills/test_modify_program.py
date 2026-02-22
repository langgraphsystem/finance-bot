"""Tests for modify_program skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.sandbox.e2b_runner import ExecutionResult
from src.gateway.types import IncomingMessage, MessageType
from src.skills.modify_program.handler import ModifyProgramSkill


@pytest.fixture
def skill():
    return ModifyProgramSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1", user_id="tg_1", chat_id="chat_1",
        type=MessageType.text, text=text,
    )


def _mock_redis_with_code(ctx, prog_id="abc123", code="print('old')"):
    """Create a mock Redis that returns stored code and accepts setex."""
    payload = f"calculator.py\n---\n{code}"
    mock = MagicMock()
    mock.get = AsyncMock(side_effect=lambda key: {
        f"user_last_program:{ctx.user_id}": prog_id,
        f"program:{prog_id}": payload,
    }.get(key))
    mock.setex = AsyncMock()
    return mock


async def test_empty_changes_asks(skill, ctx):
    """Empty changes returns prompt."""
    result = await skill.execute(_msg(""), ctx, {})
    text = result.response_text.lower()
    assert "changes" in text or "modifications" in text


async def test_no_program_found(skill, ctx):
    """No program in Redis returns 'generate first' message."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    with patch("src.skills.modify_program.handler.redis", mock_redis):
        result = await skill.execute(
            _msg("change the color to blue"),
            ctx,
            {"program_changes": "change the color to blue"},
        )
    assert "generate" in result.response_text.lower()


async def test_finds_program_by_last_id(skill, ctx):
    """user_last_program lookup works."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified calculator for testing\nprint("new")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        result = await skill.execute(
            _msg("change color"), ctx, {"program_changes": "change color"},
        )

    assert result.document is not None
    assert result.document_name == "calculator.py"


async def test_finds_program_by_explicit_id(skill, ctx):
    """Explicit program_id in intent_data works."""
    payload = "calc.py\n---\nprint('hello')"
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(side_effect=lambda key: {
        "program:xyz789": payload,
    }.get(key))
    mock_redis.setex = AsyncMock()
    modified = '# Modified for testing\nprint("changed")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        result = await skill.execute(
            _msg("fix the bug"),
            ctx,
            {"program_changes": "fix the bug", "program_id": "xyz789"},
        )

    assert result.document is not None


async def test_modified_code_saved_to_redis(skill, ctx):
    """New prog_id saved + user_last_program updated."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified calculator for testing\nprint("new")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        await skill.execute(
            _msg("update"), ctx, {"program_changes": "update the output"},
        )

    # setex called twice: program:{new_id} + user_last_program
    assert mock_redis.setex.call_count == 2
    key0 = mock_redis.setex.call_args_list[0][0][0]
    key1 = mock_redis.setex.call_args_list[1][0][0]
    assert key0.startswith("program:")
    assert key1.startswith("user_last_program:")


async def test_e2b_execution_with_url(skill, ctx):
    """Modified code runs in E2B, URL in response."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified web app for testing\nfrom flask import Flask\napp = Flask(__name__)'
    exec_result = ExecutionResult(url="https://5000-mod.e2b.app")

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.execute_code",
            new_callable=AsyncMock,
            return_value=exec_result,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner._is_web_app",
            return_value=True,
        ),
    ):
        result = await skill.execute(
            _msg("add dark mode"), ctx, {"program_changes": "add dark mode"},
        )

    assert "https://5000-mod.e2b.app" in result.response_text
    assert "Open app" in result.response_text


async def test_fallback_sends_document(skill, ctx):
    """Without E2B, modified code sent as document."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified for testing\nprint("new")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        result = await skill.execute(
            _msg("fix"), ctx, {"program_changes": "fix the bug"},
        )

    assert result.document is not None
    assert "(modified)" in result.response_text


async def test_mem0_background_task_present(skill, ctx):
    """Background Mem0 task is added to result."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified for testing\nprint("new")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        result = await skill.execute(
            _msg("fix"), ctx, {"program_changes": "fix the bug"},
        )

    assert len(result.background_tasks) == 1
    assert callable(result.background_tasks[0])


async def test_code_button_present(skill, ctx):
    """Response includes Code button with show_code callback."""
    mock_redis = _mock_redis_with_code(ctx)
    modified = '# Modified for testing\nprint("new")'

    with (
        patch("src.skills.modify_program.handler.redis", mock_redis),
        patch(
            "src.skills.modify_program.handler.generate_text",
            new_callable=AsyncMock,
            return_value=modified,
        ),
        patch(
            "src.skills.modify_program.handler.e2b_runner.is_configured",
            return_value=False,
        ),
    ):
        result = await skill.execute(
            _msg("fix"), ctx, {"program_changes": "fix"},
        )

    assert result.buttons is not None
    assert any("Code" in b["text"] for b in result.buttons)
    assert any(b["callback"].startswith("show_code:") for b in result.buttons)
