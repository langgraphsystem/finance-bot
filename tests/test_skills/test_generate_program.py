"""Tests for generate_program skill (v3 — web-first, code on request)."""

import html as html_mod
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.sandbox.e2b_runner import ExecutionResult
from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_program.handler import (
    MAX_FIX_ATTEMPTS,
    GenerateProgramSkill,
    _detect_extension,
    _extract_description,
    _make_filename,
    _select_model,
    _strip_markdown_fences,
    _wrap_html_as_flask,
)


@pytest.fixture
def skill():
    return GenerateProgramSkill()


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
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def _patch_gen(return_value: str):
    return patch(
        "src.skills.generate_program.handler.generate_text",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _patch_redis():
    """Mock Redis setex for code storage."""
    return patch(
        "src.skills.generate_program.handler.redis",
        setex=AsyncMock(),
    )


def _patch_e2b_off():
    """Disable E2B execution."""
    return patch(
        "src.skills.generate_program.handler.e2b_runner.is_configured",
        return_value=False,
    )


def _patch_e2b_on(result: ExecutionResult):
    """Enable E2B execution with a given result."""
    return (
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=False,
        ),
    )


def _patch_e2b_on_web(result: ExecutionResult):
    """Enable E2B execution as a web app."""
    return (
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=True,
        ),
    )


# --- Core skill tests ---


async def test_fallback_sends_document(skill, ctx):
    """Without E2B key, code is sent as document (fallback)."""
    code = '"""Calorie tracker."""\nfrom flask import Flask\napp = Flask(__name__)'
    with _patch_gen(code), _patch_e2b_off(), _patch_redis():
        result = await skill.execute(
            _msg("калькулятор калорий"),
            ctx,
            {"program_description": "калькулятор калорий"},
        )

    assert result.document is not None
    assert result.document_name.endswith(".py")
    assert result.document == code.encode("utf-8")


async def test_generates_js_extension(skill, ctx):
    """Uses .js extension when JavaScript is specified."""
    code = 'console.log("hello");'
    with _patch_gen(code), _patch_e2b_off(), _patch_redis():
        result = await skill.execute(
            _msg("write a JS script"),
            ctx,
            {"program_description": "hello world", "program_language": "javascript"},
        )

    assert result.document_name.endswith(".js")


async def test_strips_markdown_fences(skill, ctx):
    """Markdown fences are stripped from LLM output."""
    raw = '```python\nprint("hello")\n```'
    with _patch_gen(raw), _patch_e2b_off(), _patch_redis():
        result = await skill.execute(
            _msg("hello world"),
            ctx,
            {"program_description": "hello world"},
        )

    assert result.document == b'print("hello")'


async def test_empty_description_asks_for_details(skill, ctx):
    """Empty description returns a prompt asking what to generate."""
    result = await skill.execute(_msg(""), ctx, {})

    assert (
        "describe" in result.response_text.lower()
        or "program" in result.response_text.lower()
    )
    assert result.document is None


async def test_model_is_sonnet(skill):
    """Skill default model is Claude Sonnet 4.6."""
    assert skill.model == "claude-sonnet-4-6"


# --- Multi-model routing tests ---


async def test_routes_python_to_sonnet(skill, ctx):
    """Python code routes to Claude Sonnet 4.6."""
    code = 'print("hello")'
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("write a python script"),
            ctx,
            {"program_description": "hello world", "program_language": "python"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "claude-sonnet-4-6"


async def test_routes_bash_to_gpt(skill, ctx):
    """Bash code routes to GPT-5.2."""
    code = '#!/bin/bash\necho "hello"'
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("write a bash script"),
            ctx,
            {"program_description": "backup script", "program_language": "bash"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gpt-5.2"


async def test_routes_html_to_gemini(skill, ctx):
    """HTML code routes to Gemini 3 Flash."""
    code = "<!DOCTYPE html><html><body>Hello</body></html>"
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("create an HTML page"),
            ctx,
            {"program_description": "landing page", "program_language": "html"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gemini-3-flash-preview"


async def test_routes_docker_description_to_gpt(skill, ctx):
    """Docker-related description routes to GPT-5.2 even without language."""
    code = 'FROM python:3.12\nCOPY . .\nCMD ["python", "app.py"]'
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("create a dockerfile"),
            ctx,
            {"program_description": "dockerfile for my flask app"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gpt-5.2"


async def test_routes_react_description_to_gemini(skill, ctx):
    """React-related description routes to Gemini 3 Flash."""
    code = "import React from 'react';\nexport default function App() {}"
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("make a react component"),
            ctx,
            {"program_description": "react component for todo list"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gemini-3-flash-preview"


# --- E2B execution tests (v3 — web-first) ---


async def test_web_app_url_no_document(skill, ctx):
    """Web app URL appears in response, no document attached."""
    code = 'from flask import Flask\napp = Flask(__name__)\napp.run()'
    exec_result = ExecutionResult(url="https://5000-abc123.e2b.app")
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on_web(exec_result)

    with _patch_gen(code), p_cfg, p_exec, p_lang, p_web, _patch_redis():
        result = await skill.execute(
            _msg("flask app"),
            ctx,
            {"program_description": "flask hello world"},
        )

    assert "https://5000-abc123.e2b.app" in result.response_text
    assert "Open app" in result.response_text
    assert result.document is None  # No document by default


async def test_execution_output_shown(skill, ctx):
    """Successful execution output appears in response."""
    code = '# Simple hello world script for testing\nprint("Hello World")'
    exec_result = ExecutionResult(stdout="Hello World\n")
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec, p_lang, p_web, _patch_redis():
        result = await skill.execute(
            _msg("hello world script"),
            ctx,
            {"program_description": "hello world"},
        )

    assert "Hello World" in result.response_text
    assert "<b>Output:</b>" in result.response_text
    assert result.document is None  # No document by default


async def test_show_code_button_present(skill, ctx):
    """Response includes inline Code button."""
    code = '# Simple hello world script for testing\nprint("Hello World")'
    exec_result = ExecutionResult(stdout="Hello World\n")
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec, p_lang, p_web, _patch_redis():
        result = await skill.execute(
            _msg("hello world"),
            ctx,
            {"program_description": "hello world"},
        )

    assert result.buttons is not None
    assert len(result.buttons) >= 1
    btn = result.buttons[0]
    assert "Code" in btn["text"]
    assert btn["callback"].startswith("show_code:")


async def test_code_saved_to_redis(skill, ctx):
    """Code is saved to Redis with program: prefix and TTL."""
    code = '# Simple hello world script for testing\nprint("Hello World")'
    mock_redis = AsyncMock()

    with (
        _patch_gen(code),
        _patch_e2b_off(),
        patch("src.skills.generate_program.handler.redis", mock_redis),
    ):
        await skill.execute(
            _msg("hello"),
            ctx,
            {"program_description": "hello world"},
        )

    assert mock_redis.setex.call_count == 2
    # First call: program:{id}
    key0 = mock_redis.setex.call_args_list[0][0][0]
    ttl0 = mock_redis.setex.call_args_list[0][0][1]
    payload = mock_redis.setex.call_args_list[0][0][2]
    assert key0.startswith("program:")
    assert ttl0 == 86400
    assert "\n---\n" in payload
    assert 'print("Hello World")' in payload
    # Second call: user_last_program:{user_id}
    key1 = mock_redis.setex.call_args_list[1][0][0]
    assert key1.startswith("user_last_program:")


async def test_auto_retry_on_error_success(skill, ctx):
    """Auto-retry: first execution fails, fixed code succeeds."""
    original_code = "broken code"
    fixed_code = '# Fixed working script for testing\nprint("fixed")'

    # First call returns original code, second call returns fixed code
    gen_mock = AsyncMock(side_effect=[original_code, fixed_code])

    fail_result = ExecutionResult(error="SyntaxError: invalid syntax")
    ok_result = ExecutionResult(stdout="fixed\n")

    exec_mock = AsyncMock(side_effect=[fail_result, ok_result])

    with (
        patch("src.skills.generate_program.handler.generate_text", gen_mock),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=False,
        ),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("test"), ctx, {"program_description": "test program"},
        )

    # generate_text called twice: original + fix
    assert gen_mock.call_count == 2
    # execute_code called twice: original + fixed
    assert exec_mock.call_count == 2
    # Response shows success (not error)
    assert "fixed" in result.response_text


async def test_auto_retry_exhausts_all_attempts(skill, ctx):
    """Auto-retry: all fix attempts fail — error shown."""
    code = "broken code"
    gen_mock = AsyncMock(return_value=code)

    fail_result = ExecutionResult(error="SyntaxError: invalid syntax")
    exec_mock = AsyncMock(return_value=fail_result)

    with (
        patch("src.skills.generate_program.handler.generate_text", gen_mock),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=False,
        ),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("test"), ctx, {"program_description": "test program"},
        )

    # 1 original + MAX_FIX_ATTEMPTS fix attempts
    assert gen_mock.call_count == 1 + MAX_FIX_ATTEMPTS
    assert exec_mock.call_count == 1 + MAX_FIX_ATTEMPTS
    assert "SyntaxError" in result.response_text
    assert "&lt;" not in result.response_text or "<b>Error:</b>" in result.response_text


async def test_no_retry_on_timeout(skill, ctx):
    """Timeout does NOT trigger auto-retry."""
    code = "import time\ntime.sleep(100)"
    exec_result = ExecutionResult(
        timed_out=True,
        error="Execution timed out after 30s",
    )
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on(exec_result)

    with _patch_gen(code) as mock_gen, p_cfg, p_exec, p_lang, p_web, _patch_redis():
        result = await skill.execute(
            _msg("slow script"),
            ctx,
            {"program_description": "slow script"},
        )

    # Only one generate_text call — no retry
    mock_gen.assert_called_once()
    assert "timed out" in result.response_text.lower()


async def test_no_execution_without_api_key(skill, ctx):
    """Without E2B key, document is returned (no execution output)."""
    code = 'print("hello")'
    with _patch_gen(code), _patch_e2b_off(), _patch_redis():
        result = await skill.execute(
            _msg("hello"),
            ctx,
            {"program_description": "hello"},
        )

    assert result.document is not None
    assert "<b>Output:</b>" not in result.response_text
    assert "Open app" not in result.response_text


async def test_web_timeout_60s(skill, ctx):
    """Web apps get 60s timeout instead of default 30s."""
    code = 'from flask import Flask\napp = Flask(__name__)\napp.run()'
    exec_result = ExecutionResult(url="https://5000-abc.e2b.app")

    exec_mock = AsyncMock(return_value=exec_result)

    with (
        _patch_gen(code),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=True,
        ),
        _patch_redis(),
    ):
        await skill.execute(
            _msg("flask app"), ctx, {"program_description": "flask hello"},
        )

    exec_mock.assert_called_once()
    assert exec_mock.call_args.kwargs["timeout"] == 60


# --- Unit tests for _select_model ---


def test_select_model_python():
    assert _select_model("python", "anything") == "claude-sonnet-4-6"


def test_select_model_bash():
    assert _select_model("bash", "anything") == "gpt-5.2"


def test_select_model_javascript():
    assert _select_model("javascript", "anything") == "gemini-3-flash-preview"


def test_select_model_docker_from_description():
    assert _select_model("", "create a dockerfile") == "gpt-5.2"


def test_select_model_react_from_description():
    assert _select_model("", "build a react component") == "gemini-3-flash-preview"


def test_select_model_default():
    assert _select_model("", "some program") == "claude-sonnet-4-6"


# --- Unit tests for _extract_description ---


def test_extract_description_docstring():
    code = '"""Calorie tracker with BMR formula."""\nfrom flask import Flask'
    assert _extract_description(code) == "Calorie tracker with BMR formula."


def test_extract_description_comment():
    code = "# Simple calculator for daily calorie needs\nfrom flask import Flask"
    assert _extract_description(code) == "Simple calculator for daily calorie needs"


def test_extract_description_html_title():
    code = "<!DOCTYPE html><html><head><title>Calorie Calculator</title></head>"
    assert _extract_description(code) == "Calorie Calculator"


def test_extract_description_short_ignored():
    code = "# short\nfrom flask import Flask"
    assert _extract_description(code) == ""


def test_extract_description_empty():
    code = "from flask import Flask\napp = Flask(__name__)"
    assert _extract_description(code) == ""


def test_extract_description_shebang_skipped():
    code = "#!/usr/bin/env python3\n# Useful calculator app for testing\nprint(1)"
    assert _extract_description(code) == "Useful calculator app for testing"


# --- Unit tests for helper functions ---


def test_strip_markdown_fences_python():
    raw = '```python\nimport os\nprint(os.getcwd())\n```'
    assert _strip_markdown_fences(raw) == "import os\nprint(os.getcwd())"


def test_strip_markdown_fences_no_fences():
    raw = 'print("hello")'
    assert _strip_markdown_fences(raw) == 'print("hello")'


def test_strip_markdown_fences_bash():
    raw = '```bash\n#!/bin/bash\necho "hi"\n```'
    assert _strip_markdown_fences(raw) == '#!/bin/bash\necho "hi"'


def test_detect_extension_from_language():
    assert _detect_extension("code", "python") == ".py"
    assert _detect_extension("code", "javascript") == ".js"
    assert _detect_extension("code", "bash") == ".sh"


def test_detect_extension_from_shebang():
    assert _detect_extension("#!/bin/bash\necho hi", "") == ".sh"
    assert _detect_extension("#!/usr/bin/env python3\nprint(1)", "") == ".py"
    assert _detect_extension("#!/usr/bin/env node\nconsole.log(1)", "") == ".js"


def test_detect_extension_from_content():
    assert _detect_extension("<!DOCTYPE html>\n<html>", "") == ".html"
    assert _detect_extension("package main\nfunc main() {}", "") == ".go"
    assert _detect_extension("fn main() {\n}", "") == ".rs"


def test_detect_extension_defaults_to_python():
    assert _detect_extension("some random code", "") == ".py"


def test_make_filename_cyrillic():
    name = _make_filename("парсер для avito", ".py")
    assert name.endswith(".py")
    assert "avito" in name
    assert name.isascii()


def test_make_filename_english():
    name = _make_filename("calorie tracker app", ".py")
    assert name == "calorie_tracker_app.py"


def test_make_filename_empty():
    name = _make_filename("", ".py")
    assert name == "program.py"


def test_make_filename_truncates_long():
    name = _make_filename("a" * 100, ".py")
    assert len(name) <= 44  # 40 chars + ".py"


# --- HTML wrapping tests ---


def test_wrap_html_as_flask_produces_runnable_python():
    """Wrapped HTML produces valid Python with Flask."""
    html = "<!DOCTYPE html><html><body><h1>Hello</h1></body></html>"
    wrapped = _wrap_html_as_flask(html)
    assert "from flask import Flask" in wrapped
    assert "app.run(" in wrapped
    assert "host='0.0.0.0'" in wrapped
    assert "base64" in wrapped
    # Must be valid Python (no SyntaxError)
    compile(wrapped, "<test>", "exec")


def test_wrap_html_preserves_css_with_degrees():
    """CSS with linear-gradient(135deg, ...) survives wrapping."""
    html = (
        "<style>body{background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);}"
        "</style><h1>Test</h1>"
    )
    wrapped = _wrap_html_as_flask(html)
    compile(wrapped, "<test>", "exec")  # No SyntaxError

    # Verify roundtrip
    import base64

    # Extract the base64 string and verify it decodes to original HTML
    import re

    m = re.search(r'base64\.b64decode\("([^"]+)"\)', wrapped)
    assert m
    decoded = base64.b64decode(m.group(1)).decode("utf-8")
    assert decoded == html


async def test_html_file_wrapped_for_e2b(skill, ctx):
    """HTML files are wrapped in Flask before E2B execution."""
    html_code = "<!DOCTYPE html><html><body><h1>Calorie Calc</h1></body></html>"
    exec_result = ExecutionResult(url="https://5000-abc.e2b.app")

    exec_mock = AsyncMock(return_value=exec_result)

    with (
        _patch_gen(html_code),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("напиши калькулятор калорий"),
            ctx,
            {"program_description": "калькулятор калорий", "program_language": "html"},
        )

    # E2B received wrapped Python code, not raw HTML
    call_code = exec_mock.call_args[0][0]
    assert "from flask import Flask" in call_code
    assert "base64" in call_code
    assert exec_mock.call_args[1]["language"] == "python"
    assert exec_mock.call_args[1]["timeout"] == 60  # web app timeout

    # Response shows the URL
    assert "https://5000-abc.e2b.app" in result.response_text


# --- Bug fix regression tests ---


async def test_xss_in_stdout_escaped(skill, ctx):
    """stdout containing HTML tags is escaped in response (XSS fix)."""
    code = '# Simple hello world script for testing\nprint("<img onerror=alert(1)>")'
    malicious_output = '</code><script>alert(1)</script><code>'
    exec_result = ExecutionResult(stdout=malicious_output)
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec, p_lang, p_web, _patch_redis():
        result = await skill.execute(
            _msg("hello"), ctx, {"program_description": "hello"},
        )

    # Raw HTML must NOT appear — it must be escaped
    assert "<script>" not in result.response_text
    assert html_mod.escape(malicious_output) in result.response_text


async def test_xss_in_error_escaped(skill, ctx):
    """Error messages containing HTML tags are escaped (XSS fix)."""
    code = "broken"
    malicious_error = '<img src=x onerror="alert(1)">'
    exec_result = ExecutionResult(error=malicious_error)
    p_cfg, p_exec, p_lang, p_web = _patch_e2b_on(exec_result)

    gen_mock = AsyncMock(return_value=code)
    with (
        patch("src.skills.generate_program.handler.generate_text", gen_mock),
        p_cfg, p_exec, p_lang, p_web, _patch_redis(),
    ):
        result = await skill.execute(
            _msg("test"), ctx, {"program_description": "test"},
        )

    assert 'onerror="alert(1)"' not in result.response_text
    assert html_mod.escape(malicious_error) in result.response_text


async def test_css_file_not_wrapped_in_flask(skill, ctx):
    """CSS files should NOT be wrapped in Flask (CSS wrapping fix)."""
    css_code = "body { background: #333; color: #fff; }"
    exec_result = ExecutionResult(stdout="")
    exec_mock = AsyncMock(return_value=exec_result)

    with (
        _patch_gen(css_code),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=False,
        ),
        _patch_redis(),
    ):
        await skill.execute(
            _msg("dark mode stylesheet"),
            ctx,
            {"program_description": "dark mode stylesheet", "program_language": "css"},
        )

    # E2B received raw CSS, NOT Flask-wrapped code
    call_code = exec_mock.call_args[0][0]
    assert "from flask import Flask" not in call_code
    assert "body" in call_code


async def test_description_fallback_skips_generic_field(skill, ctx):
    """Handler uses program_description or message.text, never generic description."""
    code = '# Simple hello world script for testing\nprint("hello")'
    with _patch_gen(code) as mock_gen, _patch_e2b_off(), _patch_redis():
        await skill.execute(
            _msg("напиши программу калькулятор"),
            ctx,
            {"description": "$100.50"},  # generic finance field — must be ignored
        )

    # Should use message.text, not the finance-domain "description" field
    prompt_arg = mock_gen.call_args.kwargs["prompt"]
    assert "$100.50" not in prompt_arg
    assert "калькулятор" in prompt_arg


# --- Iterative fix + Mem0 tests ---


async def test_auto_retry_succeeds_on_second_attempt(skill, ctx):
    """Auto-retry: first fix fails, second fix succeeds."""
    original = "broken code"
    still_broken = "still broken"
    fixed = '# Fixed code for testing\nprint("works")'

    gen_mock = AsyncMock(side_effect=[original, still_broken, fixed])

    fail1 = ExecutionResult(error="SyntaxError")
    fail2 = ExecutionResult(error="NameError")
    ok = ExecutionResult(stdout="works\n")
    exec_mock = AsyncMock(side_effect=[fail1, fail2, ok])

    with (
        patch("src.skills.generate_program.handler.generate_text", gen_mock),
        patch(
            "src.skills.generate_program.handler.e2b_runner.is_configured",
            return_value=True,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner.execute_code",
            exec_mock,
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._map_language",
            return_value="python",
        ),
        patch(
            "src.skills.generate_program.handler.e2b_runner._is_web_app",
            return_value=False,
        ),
        _patch_redis(),
    ):
        result = await skill.execute(
            _msg("test"), ctx, {"program_description": "test program"},
        )

    assert gen_mock.call_count == 3  # original + 2 fixes
    assert exec_mock.call_count == 3
    assert "works" in result.response_text


async def test_mem0_background_task_added(skill, ctx):
    """Successful generation adds Mem0 background task."""
    code = '# Simple hello world script for testing\nprint("hello")'
    with _patch_gen(code), _patch_e2b_off(), _patch_redis():
        result = await skill.execute(
            _msg("hello"),
            ctx,
            {"program_description": "hello world", "program_language": "python"},
        )

    assert len(result.background_tasks) == 1
    assert callable(result.background_tasks[0])


async def test_mem0_stores_program_description(skill, ctx):
    """Background task calls add_memory with program description."""
    code = '# Simple hello world script for testing\nprint("hello")'
    with (
        _patch_gen(code),
        _patch_e2b_off(),
        _patch_redis(),
        patch(
            "src.skills.generate_program.handler.add_memory",
            new_callable=AsyncMock,
        ) as mock_mem0,
    ):
        result = await skill.execute(
            _msg("калькулятор калорий"),
            ctx,
            {"program_description": "калькулятор калорий", "program_language": "python"},
        )
        # Execute the background task inside the patch context
        await result.background_tasks[0]()

        mock_mem0.assert_called_once()
        content = mock_mem0.call_args.kwargs["content"]
        assert "калькулятор калорий" in content
        assert mock_mem0.call_args.kwargs["user_id"] == ctx.user_id
