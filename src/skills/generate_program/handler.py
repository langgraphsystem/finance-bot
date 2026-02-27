"""Generate program skill — web-first code generation.

Routes to the best LLM by language/task type:
- Python/Go/Rust/SQL → Claude Sonnet 4.6
- Bash/Docker/YAML → GPT-5.2
- HTML/CSS/JS/TS → Gemini 3 Flash

Always generates web-based apps (Flask/HTML). Runs in E2B sandbox
and sends a public URL. Code available via inline button on request.
"""

import base64
import html as html_mod
import logging
import re
import unicodedata
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

logger = logging.getLogger(__name__)

# TTL for stored code in Redis (24 hours)
CODE_TTL_S = 86400

# Max auto-fix attempts when E2B execution fails
MAX_FIX_ATTEMPTS = 3

CODE_GEN_SYSTEM_PROMPT = """\
You are a code generator. Create WEB-BASED programs that run in a browser.

Rules:
- For Python: ALWAYS use Flask with inline HTML templates \
(render_template_string). Never use input()/stdin.
  Minimal pattern: Flask app with routes that render HTML forms.
  CRITICAL: always use app.run(host='0.0.0.0', port=5000, debug=False).
  CRITICAL: always add "# pip install flask" comment at the very first line.
- For JavaScript: create a standalone HTML page with embedded <script>.
- For HTML/CSS: create a standalone HTML page.
- Include all HTML inline (no separate template files).
- If dependencies needed — add "# pip install flask ..." comment at top.
- Make the UI clean and simple. Use basic CSS for styling.
- The app MUST work as a single file.
- Add a brief docstring/comment at the top describing what the app does.
- DO NOT add placeholder/TODO sections — generate working code.
- Respond ONLY with code, no explanations outside the code."""

FIX_CODE_PROMPT = """\
The following code failed to run with this error:

Error: {error}

Original code:
```
{code}
```

Fix the code so it runs without errors. Keep the same functionality.
Respond ONLY with the fixed code, no explanations."""

# Maps language hints to file extensions
LANG_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "bash": ".sh",
    "shell": ".sh",
    "sh": ".sh",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "kotlin": ".kt",
    "swift": ".swift",
    "ruby": ".rb",
    "php": ".php",
    "c": ".c",
    "cpp": ".cpp",
    "c++": ".cpp",
    "csharp": ".cs",
    "c#": ".cs",
}

# Model routing by language/task type
CODE_MODEL_MAP: dict[str, str] = {
    "python": "claude-sonnet-4-6",
    "py": "claude-sonnet-4-6",
    "go": "claude-sonnet-4-6",
    "rust": "claude-sonnet-4-6",
    "sql": "claude-sonnet-4-6",
    "java": "claude-sonnet-4-6",
    "kotlin": "claude-sonnet-4-6",
    "swift": "claude-sonnet-4-6",
    "ruby": "claude-sonnet-4-6",
    "php": "claude-sonnet-4-6",
    "c": "claude-sonnet-4-6",
    "cpp": "claude-sonnet-4-6",
    "c++": "claude-sonnet-4-6",
    "csharp": "claude-sonnet-4-6",
    "c#": "claude-sonnet-4-6",
    "bash": "gpt-5.2",
    "shell": "gpt-5.2",
    "sh": "gpt-5.2",
    "docker": "gpt-5.2",
    "yaml": "gpt-5.2",
    "javascript": "gemini-3-flash-preview",
    "js": "gemini-3-flash-preview",
    "typescript": "gemini-3-flash-preview",
    "ts": "gemini-3-flash-preview",
    "html": "gemini-3-flash-preview",
    "css": "gemini-3-flash-preview",
}

_INFRA_KEYWORDS = {
    "bash", "shell", "docker", "dockerfile", "nginx",
    "deploy", "ci/cd", "ci-cd", "github actions", "cron",
    "backup", "migration", "devops", "ansible", "terraform",
}

_FRONTEND_KEYWORDS = {
    "html", "css", "react", "frontend", "ui", "webpage",
    "website", "landing", "page", "web page", "svg",
    "animation", "tailwind", "component",
}


def _select_model(language: str, description: str) -> str:
    """Pick the best model for the given language and description."""
    if language and language in CODE_MODEL_MAP:
        return CODE_MODEL_MAP[language]

    desc_lower = description.lower()

    for kw in _INFRA_KEYWORDS:
        if kw in desc_lower:
            return "gpt-5.2"

    for kw in _FRONTEND_KEYWORDS:
        if kw in desc_lower:
            return "gemini-3-flash-preview"

    return "claude-sonnet-4-6"


def _extract_description(code: str) -> str:
    """Extract a brief description from the code's docstring or comment."""
    # Try Python docstring
    match = re.search(r'"""(.+?)"""', code[:500], re.DOTALL)
    if match:
        desc = match.group(1).strip().split("\n")[0]
        if len(desc) > 10:
            return desc

    # Try single-line comment (skip dependency comments)
    for line in code.split("\n")[:10]:
        line = line.strip()
        if line.startswith("#") and not line.startswith("#!"):
            desc = line.lstrip("# ").strip()
            if len(desc) > 10 and not desc.lower().startswith(("pip install", "npm install")):
                return desc

    # Try HTML comment or title
    match = re.search(r"<title>(.+?)</title>", code[:500], re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return ""


def _wrap_html_as_flask(html_code: str) -> str:
    """Wrap standalone HTML/CSS in a Flask app so E2B can serve it."""
    encoded = base64.b64encode(html_code.encode("utf-8")).decode("ascii")
    return (
        "# pip install flask\n"
        "import base64\n"
        "from flask import Flask\n"
        "\n"
        "app = Flask(__name__)\n"
        f'_HTML = base64.b64decode("{encoded}").decode("utf-8")\n'
        "\n"
        "\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return _HTML\n"
        "\n"
        "\n"
        "app.run(host='0.0.0.0', port=5000, debug=False)\n"
    )


class GenerateProgramSkill:
    name = "generate_program"
    intents = ["generate_program"]
    model = "claude-sonnet-4-6"

    @observe(name="generate_program")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        description = (
            intent_data.get("program_description")
            or message.text
            or ""
        ).strip()

        if not description:
            return SkillResult(
                response_text=(
                    "What program do you need? "
                    "Describe it and I'll generate the code."
                )
            )

        language = (
            intent_data.get("program_language") or ""
        ).strip().lower()

        # Select model based on language / description
        model = _select_model(language, description)
        logger.info(
            "generate_program: model=%s lang=%s desc=%.60s",
            model, language or "auto", description,
        )

        # Build prompt
        prompt = f"Create a program: {description}"
        if language:
            prompt += f"\nLanguage: {language}"

        code = await generate_text(
            model=model,
            system=CODE_GEN_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=4096,
        )
        code = _strip_markdown_fences(code)

        # Detect extension + filename
        ext = _detect_extension(code, language)
        filename = _make_filename(description, ext)

        # Save code to Redis for "show code" button
        prog_id = str(uuid.uuid4())[:8]
        code_payload = f"{filename}\n---\n{code}"
        await redis.setex(
            f"program:{prog_id}", CODE_TTL_S, code_payload,
        )
        # Save pointer for modify_program lookups
        await redis.setex(
            f"user_last_program:{context.user_id}", CODE_TTL_S, prog_id,
        )

        # Extract description from generated code
        code_desc = _extract_description(code)

        # Build response
        buttons = [
            {"text": "\U0001f4c4 Code", "callback": f"show_code:{prog_id}"},
        ]

        # Mem0 background task — remember what was generated
        async def _mem0_task():
            try:
                mem_text = f"Generated program: {description}"
                if language:
                    mem_text += f" (language: {language})"
                await add_memory(
                    content=mem_text,
                    user_id=context.user_id,
                    metadata={"type": "program", "language": language or "auto"},
                )
            except Exception as e:
                logger.warning("Mem0 storage for program failed: %s", e)

        # Execute in E2B sandbox if configured
        if e2b_runner.is_configured():
            # Standalone HTML/CSS can't run as Python — wrap in Flask
            is_html = ext == ".html"
            if is_html:
                run_code = _wrap_html_as_flask(code)
                e2b_lang = "python"
                is_web = True
            else:
                run_code = code
                e2b_lang = e2b_runner._map_language(ext)
                is_web = e2b_runner._is_web_app(code)
            timeout = 60 if is_web else 30

            exec_result = await e2b_runner.execute_code(
                run_code, language=e2b_lang, timeout=timeout,
            )

            # Auto-retry loop on error (up to MAX_FIX_ATTEMPTS)
            for attempt in range(MAX_FIX_ATTEMPTS):
                if not exec_result.error or exec_result.timed_out:
                    break
                logger.info(
                    "Auto-retry %d/%d: fixing code after error",
                    attempt + 1, MAX_FIX_ATTEMPTS,
                )
                fix_prompt = FIX_CODE_PROMPT.format(
                    error=exec_result.error, code=code,
                )
                fixed_code = await generate_text(
                    model=model,
                    system=CODE_GEN_SYSTEM_PROMPT,
                    prompt=fix_prompt,
                    max_tokens=4096,
                )
                fixed_code = _strip_markdown_fences(fixed_code)

                run_fixed = _wrap_html_as_flask(fixed_code) if is_html else fixed_code
                exec_result = await e2b_runner.execute_code(
                    run_fixed, language=e2b_lang, timeout=timeout,
                )

                if not exec_result.error:
                    code = fixed_code
                    code_payload = f"{filename}\n---\n{code}"
                    await redis.setex(
                        f"program:{prog_id}",
                        CODE_TTL_S,
                        code_payload,
                    )
                    break

            # Build response based on execution result
            result = _build_code_response(
                filename, code_desc, exec_result, buttons,
            )
            result.background_tasks = [_mem0_task]
            return result

        # Fallback: no E2B — send code as file
        return SkillResult(
            response_text=f"<b>{filename}</b>",
            document=code.encode("utf-8"),
            document_name=filename,
            background_tasks=[_mem0_task],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CODE_GEN_SYSTEM_PROMPT


# --- Helper functions ---


def _build_code_response(
    filename: str,
    description: str,
    exec_result: e2b_runner.ExecutionResult,
    buttons: list[dict],
) -> SkillResult:
    """Build SkillResult from E2B execution result."""
    parts: list[str] = []

    if exec_result.url:
        parts.append(f"<b>\u2705 {filename}</b>")
        if description:
            parts.append(f"\n{description}")
        parts.append(
            f'\n\U0001f310 <a href="{exec_result.url}">'
            f"Open app</a>"
            f"\n<i>(active ~5 min)</i>"
        )
    elif exec_result.error:
        err = html_mod.escape(_truncate(exec_result.error, 500))
        parts.append(f"<b>\u274c {filename}</b>")
        parts.append(f"\n<b>Error:</b>\n<code>{err}</code>")
    elif exec_result.stdout:
        out = html_mod.escape(_truncate(exec_result.stdout, 1000))
        parts.append(f"<b>\u2705 {filename}</b>")
        if description:
            parts.append(f"\n{description}")
        parts.append(f"\n<b>Output:</b>\n<code>{out}</code>")
    else:
        parts.append(f"<b>\u2705 {filename}</b>")
        if description:
            parts.append(f"\n{description}")

    if exec_result.timed_out:
        parts.append("\n<i>Execution timed out</i>")

    return SkillResult(
        response_text="\n".join(parts),
        buttons=buttons,
    )


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _strip_markdown_fences(text: str) -> str:
    """Remove ```language ... ``` wrappers from LLM output."""
    text = text.strip()
    match = re.match(r"^```\w*\n(.*?)```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _detect_extension(code: str, language: str) -> str:
    """Detect file extension from language hint or code content."""
    if language and language in LANG_EXTENSIONS:
        return LANG_EXTENSIONS[language]

    first_line = code.split("\n", 1)[0].strip()

    if first_line.startswith("#!/") and "bash" in first_line:
        return ".sh"
    if first_line.startswith("#!/") and "python" in first_line:
        return ".py"
    if first_line.startswith("#!/") and "node" in first_line:
        return ".js"

    lower200 = code[:200].lower()
    if "<!doctype html" in lower200 or "<html" in lower200:
        return ".html"
    if "import React" in code[:300] or "from 'react'" in code[:300]:
        return ".tsx"
    if "package main" in code[:200]:
        return ".go"
    if "fn main()" in code[:200]:
        return ".rs"

    return ".py"


_STRIP_PREFIXES = (
    "напиши программу ", "напиши скрипт ", "напиши код ",
    "создай программу ", "создай скрипт ", "создай код ",
    "сделай программу ", "сделай скрипт ", "сделай ",
    "сгенерируй ", "напиши ", "создай ", "generate ", "build ",
    "write a program ", "write a script ", "write a ",
    "create a program ", "create a script ", "create a ",
    "make a ", "code a ",
)


def _make_filename(description: str, ext: str) -> str:
    """Generate a slug filename from the description."""
    text = description.lower().strip()
    for prefix in _STRIP_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text[:60]
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }
    slug = ""
    for ch in text:
        if ch in translit:
            slug += translit[ch]
        elif ch.isascii() and (ch.isalnum() or ch in " _-"):
            slug += ch
        elif ch == " ":
            slug += "_"
        else:
            nfkd = unicodedata.normalize("NFKD", ch)
            slug += "".join(c for c in nfkd if c.isascii())

    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")

    if not slug:
        slug = "program"

    if len(slug) > 40:
        slug = slug[:40].rstrip("_")

    return f"{slug}{ext}"


skill = GenerateProgramSkill()
