"""Tests for generate_program skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_program.handler import (
    GenerateProgramSkill,
    _detect_extension,
    _make_filename,
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


@pytest.mark.asyncio
async def test_generates_python_file(skill, ctx):
    """Generates a .py file and returns as document."""
    code = '#!/usr/bin/env python3\n"""Calorie tracker."""\nprint("hello")'
    with patch(
        "src.skills.generate_program.handler.generate_text",
        new_callable=AsyncMock,
        return_value=code,
    ):
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
    with patch(
        "src.skills.generate_program.handler.generate_text",
        new_callable=AsyncMock,
        return_value=code,
    ):
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
    with patch(
        "src.skills.generate_program.handler.generate_text",
        new_callable=AsyncMock,
        return_value=raw,
    ):
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

    assert "describe" in result.response_text.lower() or "program" in result.response_text.lower()
    assert result.document is None


@pytest.mark.asyncio
async def test_model_is_sonnet(skill):
    """Skill uses Claude Sonnet 4.6."""
    assert skill.model == "claude-sonnet-4-6"


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
