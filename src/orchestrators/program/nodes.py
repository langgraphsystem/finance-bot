"""Program orchestrator nodes.

Node chain:
    planner → generate_code → test_sandbox → review_quality
                  ↑               |
                  └── revise ─────┘ (max 2)
                                  ↓
                              finalize → END
"""

import logging
import uuid

from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.orchestrators.program.state import ProgramState
from src.orchestrators.resilience import with_retry, with_timeout
from src.skills.generate_program.handler import (
    CODE_GEN_SYSTEM_PROMPT,
    FIX_CODE_PROMPT,
    _detect_extension,
    _make_filename,
    _select_model,
    _strip_markdown_fences,
    _wrap_html_as_flask,
)

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM = """\
You are an expert software architect. Analyze the user's programming request and \
produce a structured plan. Respond in this format:

LANGUAGE: <language>
ARCHITECTURE: <1-2 sentence high-level design>
REQUIREMENTS:
- <requirement 1>
- <requirement 2>
- ...

Rules:
- Language must be one of: python, javascript, typescript, bash, html, go, rust, sql
- Default to python if unclear
- List only concrete, implementable requirements
- Keep each requirement to one line"""

_REVIEW_SYSTEM = """\
You are a code reviewer. Quickly check if the provided code:
1. Has obvious syntax errors
2. Is complete (not just a stub)
3. Matches the requirements

Respond with a JSON list of issues (empty if none):
["issue 1", "issue 2"]
If code looks good, respond: []"""


@with_timeout(30)
@with_retry(max_retries=1)
@observe(name="program_planner")
async def planner(state: ProgramState) -> ProgramState:
    """Decompose the request into language + structured requirements."""
    message = state.get("message_text", "")
    language_hint = state.get("program_language", "")

    prompt = f"Analyze this programming request:\n{message}"
    if language_hint:
        prompt += f"\nRequested language: {language_hint}"

    response = await generate_text(
        model="claude-opus-4-6",
        system=_PLANNER_SYSTEM,
        prompt=prompt,
        max_tokens=1024,
    )

    # Parse language and requirements from response
    language = language_hint or "python"
    requirements = message  # fallback

    lines = response.strip().splitlines()
    req_lines: list[str] = []
    in_req = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LANGUAGE:"):
            lang_val = stripped.removeprefix("LANGUAGE:").strip().lower()
            if lang_val:
                language = lang_val
        elif stripped.startswith("REQUIREMENTS:"):
            in_req = True
        elif in_req and stripped.startswith("-"):
            req_lines.append(stripped.lstrip("- ").strip())

    if req_lines:
        requirements = "\n".join(req_lines)

    logger.info("planner: lang=%s requirements=%.80s", language, requirements)
    return {**state, "program_language": language, "requirements": requirements}


@with_timeout(45)
@with_retry(max_retries=1)
@observe(name="program_generate_code")
async def generate_code(state: ProgramState) -> ProgramState:
    """Generate code based on planner requirements. Reuses exec_result from revisions."""
    requirements = state.get("requirements") or state.get("message_text", "")
    language = state.get("program_language", "")
    revision_count = state.get("revision_count", 0)

    model = _select_model(language, requirements)

    if revision_count > 0:
        # Revision pass: fix based on execution error
        exec_result = state.get("exec_result") or {}
        error = exec_result.get("error", "Unknown error")
        prev_code = state.get("code", "")
        prompt = FIX_CODE_PROMPT.format(error=error, code=prev_code)
    else:
        prompt = f"Create a program: {requirements}"
        if language:
            prompt += f"\nLanguage: {language}"

    raw = await generate_text(
        model=model,
        system=CODE_GEN_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=4096,
    )
    code = _strip_markdown_fences(raw)

    ext = _detect_extension(code, language)
    filename = _make_filename(requirements, ext)

    # Store in Redis for "show code" button (reuse existing infrastructure)
    try:
        from src.core.db import redis

        prog_id = state.get("_prog_id") or str(uuid.uuid4())[:8]
        await redis.setex(f"program:{prog_id}", 86400, f"{filename}\n---\n{code}")
        user_id = state.get("user_id", "")
        if user_id:
            await redis.setex(f"user_last_program:{user_id}", 86400, prog_id)
    except Exception as e:
        logger.warning("Redis storage skipped: %s", e)
        prog_id = str(uuid.uuid4())[:8]

    return {
        **state,
        "code": code,
        "filename": filename,
        "_prog_id": prog_id,
        "exec_result": None,
        "sandbox_url": None,
        "revision_count": revision_count,
    }


@with_timeout(75)
@observe(name="program_test_sandbox")
async def test_sandbox(state: ProgramState) -> ProgramState:
    """Execute code in E2B sandbox. Skips if E2B not configured."""
    from src.core.sandbox import e2b_runner

    if not e2b_runner.is_configured():
        logger.debug("E2B not configured — skipping sandbox")
        return {**state, "exec_result": None, "sandbox_url": None}

    code = state.get("code", "")
    filename = state.get("filename", "program.py")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "py"

    is_html = ext == "html"
    run_code = _wrap_html_as_flask(code) if is_html else code
    e2b_lang = e2b_runner._map_language(f".{ext}")
    is_web = is_html or e2b_runner._is_web_app(code)
    timeout = 60 if is_web else 30

    try:
        result = await e2b_runner.execute_code(run_code, language=e2b_lang, timeout=timeout)
        return {
            **state,
            "exec_result": {
                "url": result.url,
                "error": result.error,
                "stdout": result.stdout,
                "timed_out": result.timed_out,
            },
            "sandbox_url": result.url,
        }
    except Exception as e:
        logger.warning("Sandbox execution failed: %s", e)
        return {**state, "exec_result": {"error": str(e)}, "sandbox_url": None}


@with_timeout(20)
@observe(name="program_review_quality")
async def review_quality(state: ProgramState) -> ProgramState:
    """Quick quality check of generated code using Claude Haiku."""
    import json

    code = state.get("code", "")
    requirements = state.get("requirements", "")

    prompt = (
        f"Requirements:\n{requirements[:500]}\n\n"
        f"Code (first 1500 chars):\n{code[:1500]}"
    )

    try:
        response = await generate_text(
            model="claude-haiku-4-5",
            system=_REVIEW_SYSTEM,
            prompt=prompt,
            max_tokens=256,
        )
        issues = json.loads(response.strip())
        if not isinstance(issues, list):
            issues = []
    except Exception as e:
        logger.warning("Quality review parse error: %s", e)
        issues = []

    return {**state, "quality_issues": issues}


def route_after_review(state: ProgramState) -> str:
    """Conditional edge: revise if exec failed and under retry limit."""
    exec_result = state.get("exec_result") or {}
    revision_count = state.get("revision_count", 0)

    if exec_result.get("error") and not exec_result.get("timed_out") and revision_count < 2:
        return "generate_code"
    return "finalize"


@observe(name="program_finalize")
async def finalize(state: ProgramState) -> ProgramState:
    """Build the final response text from execution results."""
    import html as html_mod

    filename = state.get("filename", "program.py")
    exec_result = state.get("exec_result") or {}

    url = exec_result.get("url")
    error = exec_result.get("error")
    stdout = exec_result.get("stdout", "")
    timed_out = exec_result.get("timed_out", False)

    parts: list[str] = []
    if url:
        parts.append(f"<b>✅ {filename}</b>")
        parts.append(f'\n🌐 <a href="{url}">Open app</a>')
        parts.append("<i>(active ~5 min)</i>")
    elif error:
        err = html_mod.escape(error[:500])
        parts.append(f"<b>❌ {filename}</b>")
        parts.append(f"\n<b>Error:</b>\n<code>{err}</code>")
        parts.append("\n<i>Generated with deep-agent orchestration.</i>")
    elif stdout:
        out = html_mod.escape(stdout[:1000])
        parts.append(f"<b>✅ {filename}</b>")
        parts.append(f"\n<b>Output:</b>\n<code>{out}</code>")
    else:
        # No E2B — code was generated but not run
        parts.append(f"<b>✅ {filename}</b>")
        parts.append("\n<i>Complex program generated with deep-agent planning.</i>")

    if timed_out:
        parts.append("\n<i>Execution timed out.</i>")

    quality_issues = state.get("quality_issues", [])
    if quality_issues:
        parts.append(
            "\n<i>⚠️ Review notes: " + "; ".join(quality_issues[:3]) + "</i>"
        )

    response_text = "\n".join(parts)
    return {**state, "response_text": response_text}


async def mem0_background(state: ProgramState) -> None:
    """Background Mem0 task — store what was generated."""
    from src.core.memory.mem0_client import add_memory

    try:
        lang = state.get("program_language", "")
        desc = state.get("requirements", state.get("message_text", ""))[:200]
        mem_text = f"Generated program (deep-agent): {desc}"
        if lang:
            mem_text += f" (language: {lang})"
        await add_memory(
            content=mem_text,
            user_id=state["user_id"],
            metadata={"type": "program", "language": lang, "orchestrator": "program"},
        )
    except Exception as e:
        logger.warning("Mem0 background task failed: %s", e)
