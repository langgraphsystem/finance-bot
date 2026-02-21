"""E2B sandbox runner — execute generated code safely in a cloud sandbox."""

import asyncio
import logging
import re
from dataclasses import dataclass

from src.core.config import settings

logger = logging.getLogger(__name__)

# Patterns that indicate the code starts a web server
_WEB_SERVER_PATTERNS = [
    r"app\.run\(",
    r"uvicorn\.run\(",
    r"\.listen\(\s*\d+",
    r"createServer\(",
    r"Deno\.serve\(",
    r"http\.server",
    r"BaseHTTPRequestHandler",
    r"Flask\(__name__\)",
    r"FastAPI\(\)",
    r"express\(\)",
]

# Common ports to check for web apps
_COMMON_PORTS = [3000, 5000, 8000, 8080, 8888]


@dataclass
class ExecutionResult:
    """Result of running code in an E2B sandbox."""

    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    url: str | None = None
    timed_out: bool = False
    exit_code: int | None = None


def _is_web_app(code: str) -> bool:
    """Check if the code likely starts a web server."""
    for pattern in _WEB_SERVER_PATTERNS:
        if re.search(pattern, code):
            return True
    return False


def _detect_port(code: str) -> int:
    """Try to detect which port the web app listens on."""
    # Match port=NNNN or listen(NNNN) or :NNNN
    match = re.search(r"port\s*=\s*(\d{4,5})", code)
    if match:
        return int(match.group(1))
    match = re.search(r"\.listen\(\s*(\d{4,5})", code)
    if match:
        return int(match.group(1))
    match = re.search(r"run\([^)]*port\s*=\s*(\d{4,5})", code)
    if match:
        return int(match.group(1))
    # Default ports by framework
    if "Flask" in code or "flask" in code:
        return 5000
    if "FastAPI" in code or "uvicorn" in code:
        return 8000
    if "express" in code:
        return 3000
    return 8000


def _extract_deps(code: str, language: str) -> list[str]:
    """Extract dependency install commands from code comments."""
    deps: list[str] = []
    for line in code.split("\n"):
        line = line.strip()
        if language == "python":
            # Match: # pip install flask requests
            match = re.match(r"#\s*pip install\s+(.+)", line)
            if match:
                deps.append(f"pip install {match.group(1)}")
        elif language in ("js", "javascript"):
            match = re.match(r"//\s*npm install\s+(.+)", line)
            if match:
                deps.append(f"npm install {match.group(1)}")
    return deps


def _map_language(ext: str) -> str:
    """Map file extension to E2B language identifier."""
    mapping = {
        ".py": "python",
        ".js": "js",
        ".ts": "js",
        ".sh": "bash",
        ".bash": "bash",
    }
    return mapping.get(ext, "python")


def is_configured() -> bool:
    """Check if E2B API key is configured."""
    return bool(settings.e2b_api_key)


async def execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30,
) -> ExecutionResult:
    """Run code in an E2B sandbox.

    Args:
        code: Source code to execute.
        language: E2B language identifier ("python", "js", "bash").
        timeout: Maximum execution time in seconds.

    Returns:
        ExecutionResult with stdout, stderr, optional URL.
    """
    if not settings.e2b_api_key:
        return ExecutionResult(error="E2B API key not configured")

    from e2b_code_interpreter import AsyncSandbox

    web_app = _is_web_app(code)
    result = ExecutionResult()

    try:
        sandbox = await AsyncSandbox.create(
            api_key=settings.e2b_api_key,
        )
    except Exception as e:
        logger.exception("Failed to create E2B sandbox")
        return ExecutionResult(error=f"Sandbox creation failed: {e}")

    try:
        # Install dependencies if detected
        deps = _extract_deps(code, language)
        for dep_cmd in deps:
            logger.info("Installing dependency: %s", dep_cmd)
            await sandbox.run_code(dep_cmd, language="bash", timeout=60)

        if web_app:
            # For web apps: run in background, wait briefly, get URL
            port = _detect_port(code)

            # Start the server (non-blocking — it will keep running)
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []

            async def _run():
                try:
                    execution = await sandbox.run_code(
                        code,
                        language=language,
                        timeout=timeout,
                        on_stdout=lambda out: stdout_parts.append(str(out)),
                        on_stderr=lambda err: stderr_parts.append(str(err)),
                    )
                    if execution.error:
                        result.error = str(execution.error)
                except Exception:
                    pass

            asyncio.create_task(_run())
            # Wait for the server to start
            await asyncio.sleep(3)

            # Get public URL
            try:
                host = sandbox.get_host(port)
                result.url = f"https://{host}"
            except Exception:
                logger.warning("Could not get host for port %d", port)

            result.stdout = "".join(stdout_parts)
            result.stderr = "".join(stderr_parts)

            # Don't await the task — server runs indefinitely
            # Sandbox will be cleaned up later

        else:
            # Regular script: run and wait for completion
            stdout_parts = []
            stderr_parts = []

            execution = await sandbox.run_code(
                code,
                language=language,
                timeout=timeout,
                on_stdout=lambda out: stdout_parts.append(str(out)),
                on_stderr=lambda err: stderr_parts.append(str(err)),
            )

            result.stdout = "".join(stdout_parts)
            result.stderr = "".join(stderr_parts)

            if execution.error:
                result.error = str(execution.error)

            # Also grab text output
            if execution.text and not result.stdout:
                result.stdout = execution.text

    except TimeoutError:
        result.timed_out = True
        result.error = f"Execution timed out after {timeout}s"
    except Exception as e:
        logger.exception("E2B execution error")
        result.error = str(e)
    finally:
        if not web_app:
            try:
                await sandbox.close()
            except Exception:
                pass

    return result
