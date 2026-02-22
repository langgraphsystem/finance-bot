"""Modify program skill — edit a previously generated program.

Finds the user's last program from Redis, sends original code + modification
request to LLM, executes modified code in E2B, returns new URL + updated code.
"""

import logging
import uuid
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
from src.core.llm.clients import generate_text
from src.core.memory.mem0_client import add_memory
from src.core.observability import observe
from src.core.sandbox import e2b_runner
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.generate_program.handler import (
    CODE_GEN_SYSTEM_PROMPT,
    CODE_TTL_S,
    FIX_CODE_PROMPT,
    MAX_FIX_ATTEMPTS,
    _build_code_response,
    _detect_extension,
    _extract_description,
    _make_filename,
    _select_model,
    _strip_markdown_fences,
    _wrap_html_as_flask,
)

logger = logging.getLogger(__name__)

MODIFY_CODE_PROMPT = """\
Here is the existing program:

```
{code}
```

Modify this program according to these instructions:
{changes}

Rules:
- Keep the same overall structure and framework (Flask, standalone HTML, etc.)
- Apply ONLY the requested changes.
- Return the COMPLETE modified code, not just the changed parts.
- Respond ONLY with code, no explanations outside the code."""


class ModifyProgramSkill:
    name = "modify_program"
    intents = ["modify_program"]
    model = "claude-sonnet-4-6"

    @observe(name="modify_program")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        changes = (
            intent_data.get("program_changes")
            or message.text
            or ""
        ).strip()

        if not changes:
            return SkillResult(
                response_text=(
                    "What changes do you need? "
                    "Describe the modifications to your program."
                )
            )

        # Find the program to modify
        prog_id = intent_data.get("program_id") or ""
        code = ""
        filename = ""

        if prog_id:
            raw = await redis.get(f"program:{prog_id}")
        else:
            last_id = await redis.get(f"user_last_program:{context.user_id}")
            if last_id:
                prog_id = last_id if isinstance(last_id, str) else last_id.decode("utf-8")
                raw = await redis.get(f"program:{prog_id}")
            else:
                raw = None

        if raw:
            payload = raw if isinstance(raw, str) else raw.decode("utf-8")
            if "\n---\n" in payload:
                filename, code = payload.split("\n---\n", 1)
            else:
                filename, code = "program.py", payload

        if not code:
            return SkillResult(
                response_text=(
                    "No recent program found to modify. "
                    "Generate one first, then ask for changes."
                )
            )

        # Detect language from existing filename
        ext = ""
        if filename and "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1]
        language = (intent_data.get("program_language") or "").strip().lower()

        model = _select_model(language, changes)
        logger.info(
            "modify_program: model=%s prog_id=%s changes=%.60s",
            model, prog_id, changes,
        )

        # Build modification prompt
        prompt = MODIFY_CODE_PROMPT.format(code=code, changes=changes)

        modified_code = await generate_text(
            model=model,
            system=CODE_GEN_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=4096,
        )
        modified_code = _strip_markdown_fences(modified_code)

        if not ext:
            ext = _detect_extension(modified_code, language)
        if not filename:
            filename = _make_filename(changes, ext)

        # Save modified code to Redis with new ID
        new_prog_id = str(uuid.uuid4())[:8]
        code_payload = f"{filename}\n---\n{modified_code}"
        await redis.setex(f"program:{new_prog_id}", CODE_TTL_S, code_payload)
        await redis.setex(
            f"user_last_program:{context.user_id}", CODE_TTL_S, new_prog_id,
        )

        code_desc = _extract_description(modified_code)
        buttons = [
            {"text": "\U0001f4c4 Code", "callback": f"show_code:{new_prog_id}"},
        ]

        # Mem0 background task
        async def _mem0_task():
            try:
                await add_memory(
                    content=f"Modified program: {changes}",
                    user_id=context.user_id,
                    metadata={"type": "program_modify", "model": model},
                )
            except Exception as e:
                logger.warning("Mem0 storage for modification failed: %s", e)

        # Execute in E2B if configured
        if e2b_runner.is_configured():
            is_html = ext == ".html"
            if is_html:
                run_code = _wrap_html_as_flask(modified_code)
                e2b_lang = "python"
                is_web = True
            else:
                run_code = modified_code
                e2b_lang = e2b_runner._map_language(ext)
                is_web = e2b_runner._is_web_app(modified_code)
            timeout = 60 if is_web else 30

            exec_result = await e2b_runner.execute_code(
                run_code, language=e2b_lang, timeout=timeout,
            )

            # Auto-retry loop
            for attempt in range(MAX_FIX_ATTEMPTS):
                if not exec_result.error or exec_result.timed_out:
                    break
                logger.info(
                    "modify_program auto-retry %d/%d",
                    attempt + 1, MAX_FIX_ATTEMPTS,
                )
                fix_prompt = FIX_CODE_PROMPT.format(
                    error=exec_result.error, code=modified_code,
                )
                fixed = await generate_text(
                    model=model,
                    system=CODE_GEN_SYSTEM_PROMPT,
                    prompt=fix_prompt,
                    max_tokens=4096,
                )
                fixed = _strip_markdown_fences(fixed)

                run_fixed = _wrap_html_as_flask(fixed) if is_html else fixed
                exec_result = await e2b_runner.execute_code(
                    run_fixed, language=e2b_lang, timeout=timeout,
                )

                if not exec_result.error:
                    modified_code = fixed
                    code_payload = f"{filename}\n---\n{modified_code}"
                    await redis.setex(
                        f"program:{new_prog_id}", CODE_TTL_S, code_payload,
                    )
                    break

            result = _build_code_response(
                filename, code_desc, exec_result, buttons,
            )
            result.background_tasks = [_mem0_task]
            return result

        # Fallback: no E2B
        return SkillResult(
            response_text=f"<b>{filename}</b> (modified)",
            document=modified_code.encode("utf-8"),
            document_name=filename,
            buttons=buttons,
            background_tasks=[_mem0_task],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CODE_GEN_SYSTEM_PROMPT


skill = ModifyProgramSkill()
