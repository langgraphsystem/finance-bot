"""Tests for generate_program skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.sandbox.e2b_runner import ExecutionResult
from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_program.handler import (
    GenerateProgramSkill,
    _detect_extension,
    _make_filename,
    _select_model,
    _strip_markdown_fences,
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


def _patch_e2b_off():
    """Disable E2B execution."""
    return patch(
        "src.skills.generate_program.handler.e2b_runner.is_configured",
        return_value=False,
    )


def _patch_e2b_on(result: ExecutionResult):
    """Enable E2B execution with a given result."""
    return patch(
        "src.skills.generate_program.handler.e2b_runner.is_configured",
        return_value=True,
    ), patch(
        "src.skills.generate_program.handler.e2b_runner.execute_code",
        new_callable=AsyncMock,
        return_value=result,
    )


# --- Core skill tests ---


@pytest.mark.asyncio
async def test_generates_python_file(skill, ctx):
    """Generates a .py file and returns as document."""
    code = '#!/usr/bin/env python3\n"""Calorie tracker."""\nprint("hello")'
    with _patch_gen(code), _patch_e2b_off():
        result = await skill.execute(
            _msg("напиши калькулятор калорий"),
            ctx,
            {"program_description": "калькулятор калорий"},
        )

    assert result.document is not None
    assert result.document_name.endswith(".py")
    assert result.document == code.encode("utf-8")


@pytest.mark.asyncio
async def test_generates_js_when_requested(skill, ctx):
    """Uses .js extension when JavaScript is specified."""
    code = 'console.log("hello");'
    with _patch_gen(code), _patch_e2b_off():
        result = await skill.execute(
            _msg("write a JS script"),
            ctx,
            {"program_description": "hello world", "program_language": "javascript"},
        )

    assert result.document_name.endswith(".js")


@pytest.mark.asyncio
async def test_strips_markdown_fences(skill, ctx):
    """Markdown fences are stripped from LLM output."""
    raw = '```python\nprint("hello")\n```'
    with _patch_gen(raw), _patch_e2b_off():
        result = await skill.execute(
            _msg("hello world"),
            ctx,
            {"program_description": "hello world"},
        )

    assert result.document == b'print("hello")'


@pytest.mark.asyncio
async def test_empty_description_asks_for_details(skill, ctx):
    """Empty description returns a prompt asking what to generate."""
    result = await skill.execute(_msg(""), ctx, {})

    assert (
        "describe" in result.response_text.lower()
        or "program" in result.response_text.lower()
    )
    assert result.document is None


@pytest.mark.asyncio
async def test_model_is_sonnet(skill):
    """Skill default model is Claude Sonnet 4.6."""
    assert skill.model == "claude-sonnet-4-6"


# --- Multi-model routing tests ---


@pytest.mark.asyncio
async def test_routes_python_to_sonnet(skill, ctx):
    """Python code routes to Claude Sonnet 4.6."""
    code = 'print("hello")'
    with _patch_gen(code) as mock_gen, _patch_e2b_off():
        await skill.execute(
            _msg("write a python script"),
            ctx,
            {"program_description": "hello world", "program_language": "python"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_routes_bash_to_gpt(skill, ctx):
    """Bash code routes to GPT-5.2."""
    code = '#!/bin/bash\necho "hello"'
    with _patch_gen(code) as mock_gen, _patch_e2b_off():
        await skill.execute(
            _msg("write a bash script"),
            ctx,
            {"program_description": "backup script", "program_language": "bash"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gpt-5.2"


@pytest.mark.asyncio
async def test_routes_html_to_gemini(skill, ctx):
    """HTML code routes to Gemini 3 Flash."""
    code = "<!DOCTYPE html><html><body>Hello</body></html>"
    with _patch_gen(code) as mock_gen, _patch_e2b_off():
        await skill.execute(
            _msg("create an HTML page"),
            ctx,
            {"program_description": "landing page", "program_language": "html"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_routes_docker_description_to_gpt(skill, ctx):
    """Docker-related description routes to GPT-5.2 even without language."""
    code = "FROM python:3.12\nCOPY . .\nCMD [\"python\", \"app.py\"]"
    with _patch_gen(code) as mock_gen, _patch_e2b_off():
        await skill.execute(
            _msg("create a dockerfile"),
            ctx,
            {"program_description": "dockerfile for my flask app"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gpt-5.2"


@pytest.mark.asyncio
async def test_routes_react_description_to_gemini(skill, ctx):
    """React-related description routes to Gemini 3 Flash."""
    code = "import React from 'react';\nexport default function App() {}"
    with _patch_gen(code) as mock_gen, _patch_e2b_off():
        await skill.execute(
            _msg("make a react component"),
            ctx,
            {"program_description": "react component for todo list"},
        )

    mock_gen.assert_called_once()
    assert mock_gen.call_args.kwargs["model"] == "gemini-3-flash-preview"


# --- E2B execution tests ---


@pytest.mark.asyncio
async def test_execution_output_shown(skill, ctx):
    """Successful execution output appears in response."""
    code = 'print("Hello World")'
    exec_result = ExecutionResult(stdout="Hello World\n")
    p_cfg, p_exec = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec:
        result = await skill.execute(
            _msg("hello world script"),
            ctx,
            {"program_description": "hello world"},
        )

    assert "Hello World" in result.response_text
    assert "<b>Output:</b>" in result.response_text


@pytest.mark.asyncio
async def test_execution_error_shown(skill, ctx):
    """Execution error appears in response."""
    code = "1 / 0"
    exec_result = ExecutionResult(error="ZeroDivisionError: division by zero")
    p_cfg, p_exec = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec:
        result = await skill.execute(
            _msg("divide by zero"),
            ctx,
            {"program_description": "divide by zero"},
        )

    assert "ZeroDivisionError" in result.response_text
    assert "<b>Error:</b>" in result.response_text


@pytest.mark.asyncio
async def test_execution_web_app_url(skill, ctx):
    """Web app URL appears in response."""
    code = 'from flask import Flask\napp = Flask(__name__)\napp.run()'
    exec_result = ExecutionResult(url="https://5000-abc123.e2b.app")
    p_cfg, p_exec = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec:
        result = await skill.execute(
            _msg("flask app"),
            ctx,
            {"program_description": "flask hello world"},
        )

    assert "https://5000-abc123.e2b.app" in result.response_text
    assert "Open in browser" in result.response_text


@pytest.mark.asyncio
async def test_no_execution_without_api_key(skill, ctx):
    """Without E2B key, only file is returned (no execution output)."""
    code = 'print("hello")'
    with _patch_gen(code), _patch_e2b_off():
        result = await skill.execute(
            _msg("hello"),
            ctx,
            {"program_description": "hello"},
        )

    assert result.document is not None
    assert "<b>Output:</b>" not in result.response_text
    assert "Open in browser" not in result.response_text


@pytest.mark.asyncio
async def test_execution_timeout_shown(skill, ctx):
    """Timeout message appears in response."""
    code = "import time\ntime.sleep(100)"
    exec_result = ExecutionResult(
        timed_out=True,
        error="Execution timed out after 30s",
    )
    p_cfg, p_exec = _patch_e2b_on(exec_result)

    with _patch_gen(code), p_cfg, p_exec:
        result = await skill.execute(
            _msg("slow script"),
            ctx,
            {"program_description": "slow script"},
        )

    assert "timed out" in result.response_text.lower()


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
