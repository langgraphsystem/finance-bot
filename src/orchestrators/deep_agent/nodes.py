"""Deep Agent graph nodes.

Nodes for the multi-step deep agent orchestrator:
- plan_task: create a structured plan from the task description
- execute_step: execute the current plan step (code gen or data processing)
- validate_step: validate the step output (E2B execution or sanity checks)
- review_and_fix: analyze errors and apply targeted fixes
- finalize: assemble the final output (URL, PDF, document)
"""

import json
import logging
import re
import uuid
from typing import Any

from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.orchestrators.deep_agent.state import DeepAgentState

logger = logging.getLogger(__name__)

# --- Prompts ---

PLAN_PROMPT_CODE = """\
You are a software architect. Create a step-by-step plan for building this program.

Task: {task}
{lang_line}
Rules:
- Create 3-8 concrete steps. Each step must produce runnable code.
- Step 1 should set up the project skeleton (imports, app init, base HTML).
- Final step should integrate everything into a single working file.
- Each step builds on the previous steps' output.
- Be specific: "Add Flask route /api/users with GET/POST" not "Add API".

Respond ONLY with a JSON array of step descriptions (strings). Example:
["Set up Flask app with base HTML template", "Add user model and database", ...]"""

PLAN_PROMPT_TAX = """\
You are a tax analysis specialist. Create a step-by-step plan for this tax report.

Task: {task}
Data context: {data_context}

Rules:
- Create 3-6 concrete steps for a comprehensive tax analysis.
- Include: data review, categorization, deduction analysis, tax calculation, report.
- Each step should produce a clear output section.

Respond ONLY with a JSON array of step descriptions (strings). Example:
["Review income and expense data for the period", "Categorize deductible expenses", ...]"""

EXECUTE_STEP_CODE_PROMPT = """\
You are building a program step by step. Execute this step.

Overall task: {task}
{lang_line}
Current step ({step_num}/{total_steps}): {step_description}

{existing_code_section}

Rules:
- Generate the COMPLETE updated program file incorporating this step.
- Build on the existing code — don't discard previous work.
- The code must be a single runnable file.
- For Python web apps: use Flask with inline HTML (render_template_string).
  CRITICAL: use app.run(host='0.0.0.0', port=5000, debug=False).
  Add "# pip install flask" (and other deps) at the very first line.
- Include comments marking what this step added.
- Respond ONLY with code, no explanations."""

EXECUTE_STEP_TAX_PROMPT = """\
You are writing a section of a tax report. Complete this step.

Overall task: {task}
Current step ({step_num}/{total_steps}): {step_description}
Financial data:
{financial_data}

Previous sections:
{previous_sections}

Rules:
- Write the report section for this step.
- Use the provided financial data — NEVER make up numbers.
- Format with HTML tags for Telegram (<b>bold</b>).
- Be specific and actionable.
- Include relevant calculations and explanations.

Respond with the report section content only."""

FIX_STEP_PROMPT = """\
The code from the current step failed with this error:

Error: {error}

Current code:
```
{code}
```

Step being executed: {step_description}

Fix the code so it runs without errors. Keep the same functionality.
Apply a TARGETED fix — don't rewrite the entire program.
Respond ONLY with the complete fixed code, no explanations."""


def _parse_plan(raw: str) -> list[str]:
    """Parse LLM plan output into a list of step descriptions."""
    raw = raw.strip()
    # Try JSON parse first
    if raw.startswith("["):
        try:
            steps = json.loads(raw)
            if isinstance(steps, list) and all(isinstance(s, str) for s in steps):
                return steps[:8]  # Cap at 8 steps
        except json.JSONDecodeError:
            pass

    # Fallback: extract from markdown/numbered list
    steps = []
    for line in raw.split("\n"):
        line = line.strip()
        match = re.match(r'^(?:\d+[.)]\s*|[-•]\s*|"\s*)', line)
        if match:
            step = line[match.end() :].strip().rstrip('",')
            if step and len(step) > 5:
                steps.append(step)

    return steps[:8] if steps else ["Execute the complete task"]


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    match = re.match(r"^```\w*\n(.*?)```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


# --- Graph nodes ---


@observe(name="deep_agent_plan")
async def plan_task(state: DeepAgentState) -> dict[str, Any]:
    """Create a structured plan for the task."""
    task = state.get("task_description", "")
    skill_type = state.get("skill_type", "generate_program")
    model = "claude-opus-4-6"

    if skill_type == "generate_program":
        lang = state.get("program_language", "")
        lang_line = f"Language: {lang}" if lang else ""
        prompt = PLAN_PROMPT_CODE.format(task=task, lang_line=lang_line)
    else:
        data = state.get("financial_data", {})
        prompt = PLAN_PROMPT_TAX.format(
            task=task,
            data_context=json.dumps(data, default=str)[:2000],
        )

    raw = await generate_text(
        model=model,
        system="You create structured plans. Respond only with JSON arrays.",
        prompt=prompt,
        max_tokens=1024,
    )

    steps = _parse_plan(raw)
    plan = [{"step": desc, "status": "pending", "output": ""} for desc in steps]

    logger.info("Deep agent plan created: %d steps for %s", len(plan), skill_type)

    return {
        "plan": plan,
        "current_step_index": 0,
        "files": state.get("files", {}),
        "step_outputs": [],
        "retry_count": 0,
        "error": "",
    }


@observe(name="deep_agent_execute_step")
async def execute_step(state: DeepAgentState) -> dict[str, Any]:
    """Execute the current plan step."""
    plan = list(state.get("plan", []))
    idx = state.get("current_step_index", 0)
    task = state.get("task_description", "")
    skill_type = state.get("skill_type", "generate_program")
    model = state.get("model", "claude-sonnet-4-6")
    files = dict(state.get("files", {}))

    if idx >= len(plan):
        return {"error": "No more steps to execute"}

    step = plan[idx]
    step_desc = step["step"]
    total = len(plan)

    # Mark step as in_progress
    plan[idx] = {**step, "status": "in_progress"}

    if skill_type == "generate_program":
        lang = state.get("program_language", "")
        lang_line = f"Language: {lang}" if lang else ""

        # Build existing code section
        main_file = state.get("filename", "app.py")
        existing = files.get(main_file, "")
        if existing:
            existing_section = f"Current code ({main_file}):\n```\n{existing}\n```"
        else:
            existing_section = "No existing code yet — start from scratch."

        prompt = EXECUTE_STEP_CODE_PROMPT.format(
            task=task,
            lang_line=lang_line,
            step_num=idx + 1,
            total_steps=total,
            step_description=step_desc,
            existing_code_section=existing_section,
        )

        result = await generate_text(
            model=model,
            system="You are a code generator. Respond only with code.",
            prompt=prompt,
            max_tokens=8192,
        )
        code = _strip_fences(result)
        files[main_file] = code
        plan[idx] = {**step, "status": "done", "output": f"Generated {len(code)} chars"}
        step_outputs = list(state.get("step_outputs", []))
        step_outputs.append(code)

    else:
        # Tax report step
        data = state.get("financial_data", {})
        prev_outputs = state.get("step_outputs", [])
        prev_sections = "\n\n---\n\n".join(prev_outputs) if prev_outputs else "None yet."

        prompt = EXECUTE_STEP_TAX_PROMPT.format(
            task=task,
            step_num=idx + 1,
            total_steps=total,
            step_description=step_desc,
            financial_data=json.dumps(data, default=str)[:3000],
            previous_sections=prev_sections[:4000],
        )

        result = await generate_text(
            model=model,
            system="You are a tax analysis specialist. Use HTML formatting.",
            prompt=prompt,
            max_tokens=2048,
        )
        plan[idx] = {**step, "status": "done", "output": result[:200]}
        step_outputs = list(state.get("step_outputs", []))
        step_outputs.append(result)

    return {
        "plan": plan,
        "files": files,
        "step_outputs": step_outputs,
        "error": "",
        "retry_count": 0,
    }


@observe(name="deep_agent_validate_step")
async def validate_step(state: DeepAgentState) -> dict[str, Any]:
    """Validate the current step's output."""
    skill_type = state.get("skill_type", "generate_program")

    if skill_type == "generate_program":
        return await _validate_code(state)
    return await _validate_tax(state)


async def _validate_code(state: DeepAgentState) -> dict[str, Any]:
    """Validate generated code via E2B execution."""
    from src.core.sandbox import e2b_runner

    files = state.get("files", {})
    main_file = state.get("filename", "app.py")
    code = files.get(main_file, "")

    if not code:
        return {"error": "No code generated"}

    if not e2b_runner.is_configured():
        # No E2B — skip validation, assume success
        return {"error": ""}

    ext = state.get("ext", ".py")
    is_html = ext == ".html"

    if is_html:
        from src.skills.generate_program.handler import _wrap_html_as_flask

        run_code = _wrap_html_as_flask(code)
        e2b_lang = "python"
    else:
        run_code = code
        e2b_lang = e2b_runner._map_language(ext)

    is_web = is_html or e2b_runner._is_web_app(code)
    timeout = 60 if is_web else 30

    exec_result = await e2b_runner.execute_code(
        run_code,
        language=e2b_lang,
        timeout=timeout,
    )

    if exec_result.error and not exec_result.timed_out:
        return {"error": exec_result.error}

    return {"error": ""}


async def _validate_tax(state: DeepAgentState) -> dict[str, Any]:
    """Validate tax report section — basic sanity checks."""
    step_outputs = state.get("step_outputs", [])
    if not step_outputs:
        return {"error": "No output generated"}
    # Tax sections are text — no execution needed
    return {"error": ""}


@observe(name="deep_agent_review_fix")
async def review_and_fix(state: DeepAgentState) -> dict[str, Any]:
    """Analyze error and apply a targeted fix."""
    error = state.get("error", "")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if retry_count >= max_retries or not error:
        # Exhausted retries or no error — mark step failed and move on
        plan = list(state.get("plan", []))
        idx = state.get("current_step_index", 0)
        if idx < len(plan):
            plan[idx] = {**plan[idx], "status": "failed", "output": error}
        return {
            "plan": plan,
            "error": "",
            "retry_count": 0,
            "current_step_index": idx + 1,
        }

    # Try to fix
    skill_type = state.get("skill_type", "generate_program")
    if skill_type != "generate_program":
        # Tax report doesn't need code fixing
        plan = list(state.get("plan", []))
        idx = state.get("current_step_index", 0)
        if idx < len(plan):
            plan[idx] = {**plan[idx], "status": "failed", "output": error}
        return {
            "plan": plan,
            "error": "",
            "retry_count": 0,
            "current_step_index": idx + 1,
        }

    files = dict(state.get("files", {}))
    main_file = state.get("filename", "app.py")
    code = files.get(main_file, "")
    model = state.get("model", "claude-sonnet-4-6")
    plan = list(state.get("plan", []))
    idx = state.get("current_step_index", 0)
    step_desc = plan[idx]["step"] if idx < len(plan) else ""

    prompt = FIX_STEP_PROMPT.format(
        error=error,
        code=code,
        step_description=step_desc,
    )

    fixed = await generate_text(
        model=model,
        system="You are a code fixer. Respond only with complete fixed code.",
        prompt=prompt,
        max_tokens=8192,
    )
    fixed = _strip_fences(fixed)
    files[main_file] = fixed

    # Update step outputs
    step_outputs = list(state.get("step_outputs", []))
    if step_outputs:
        step_outputs[-1] = fixed

    return {
        "files": files,
        "step_outputs": step_outputs,
        "retry_count": retry_count + 1,
        "error": "",
    }


@observe(name="deep_agent_finalize")
async def finalize(state: DeepAgentState) -> dict[str, Any]:
    """Assemble the final output from all steps."""
    skill_type = state.get("skill_type", "generate_program")

    if skill_type == "generate_program":
        return await _finalize_code(state)
    return _finalize_tax(state)


async def _finalize_code(state: DeepAgentState) -> dict[str, Any]:
    """Finalize code generation — save to Redis, run in E2B, build response."""
    from src.core.db import redis
    from src.core.sandbox import e2b_runner
    from src.skills.generate_program.handler import (
        CODE_TTL_S,
        _build_code_response,
        _extract_description,
        _wrap_html_as_flask,
    )

    files = state.get("files", {})
    filename = state.get("filename", "app.py")
    code = files.get(filename, "")

    if not code:
        return {
            "response_text": "Failed to generate the program. Try a simpler description.",
            "buttons": [],
        }

    # Save to Redis
    prog_id = str(uuid.uuid4())[:8]
    code_payload = f"{filename}\n---\n{code}"
    await redis.setex(f"program:{prog_id}", CODE_TTL_S, code_payload)

    user_id = state.get("user_id", "")
    if user_id:
        await redis.setex(f"user_last_program:{user_id}", CODE_TTL_S, prog_id)

    code_desc = _extract_description(code)
    buttons = [{"text": "\U0001f4c4 Code", "callback": f"show_code:{prog_id}"}]

    # Plan summary
    plan = state.get("plan", [])
    done = sum(1 for s in plan if s.get("status") == "done")
    failed = sum(1 for s in plan if s.get("status") == "failed")
    plan_summary = f"Plan: {done}/{len(plan)} steps completed"
    if failed:
        plan_summary += f" ({failed} failed)"

    # Run in E2B for final URL
    if e2b_runner.is_configured():
        ext = state.get("ext", ".py")
        is_html = ext == ".html"

        if is_html:
            run_code = _wrap_html_as_flask(code)
            e2b_lang = "python"
        else:
            run_code = code
            e2b_lang = e2b_runner._map_language(ext)

        is_web = is_html or e2b_runner._is_web_app(code)
        timeout = 60 if is_web else 30

        exec_result = await e2b_runner.execute_code(
            run_code,
            language=e2b_lang,
            timeout=timeout,
        )

        result = _build_code_response(filename, code_desc, exec_result, buttons)
        response_text = f"{result.response_text}\n\n<i>{plan_summary}</i>"
        return {
            "response_text": response_text,
            "buttons": buttons,
        }

    # No E2B — return as document
    return {
        "response_text": f"<b>{filename}</b>\n\n<i>{plan_summary}</i>",
        "buttons": buttons,
        "document": code.encode("utf-8"),
        "document_name": filename,
    }


def _finalize_tax(state: DeepAgentState) -> dict[str, Any]:
    """Finalize tax report — combine all sections."""
    step_outputs = state.get("step_outputs", [])
    plan = state.get("plan", [])

    if not step_outputs:
        return {
            "response_text": "Couldn't generate the tax report. Try again.",
            "buttons": [],
        }

    # Combine sections with separators
    report = "\n\n".join(step_outputs)

    # Add disclaimer
    report += (
        "\n\n<i>This is an estimate, not professional tax advice. "
        "Consult a CPA for your specific situation.</i>"
    )

    done = sum(1 for s in plan if s.get("status") == "done")
    report += f"\n\n<i>Report: {done}/{len(plan)} sections completed</i>"

    return {
        "response_text": report,
        "buttons": [],
    }


# --- Routing functions ---


def route_after_validate(state: DeepAgentState) -> str:
    """Route after validation: next step, fix, or finalize."""
    error = state.get("error", "")

    if error:
        retry_count = state.get("retry_count", 0)
        max_retries = state.get("max_retries", 2)
        if retry_count < max_retries:
            return "review_and_fix"
        # Exhausted retries — still go to review_and_fix to mark failed + advance
        return "review_and_fix"

    # Step succeeded — check if more steps
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)

    if idx + 1 < len(plan):
        return "advance_step"

    return "finalize"


def route_after_fix(state: DeepAgentState) -> str:
    """Route after fix: re-validate or advance."""
    error = state.get("error", "")
    retry_count = state.get("retry_count", 0)

    if not error and retry_count > 0:
        # Fix was applied — re-validate
        return "validate_step"

    # Retries exhausted or step marked failed — check if more steps
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)

    if idx < len(plan):
        return "execute_step"

    return "finalize"


def advance_step(state: DeepAgentState) -> dict[str, Any]:
    """Advance to the next plan step."""
    idx = state.get("current_step_index", 0)
    return {
        "current_step_index": idx + 1,
        "retry_count": 0,
        "error": "",
    }
