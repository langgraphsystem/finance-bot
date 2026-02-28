"""E2B sandbox utilities — execute code and retrieve generated files."""

import logging

from src.core.config import settings

logger = logging.getLogger(__name__)


async def execute_code_with_file(
    code: str,
    output_filename: str,
    language: str = "python",
    timeout: int = 60,
    install_deps: list[str] | None = None,
) -> tuple[bytes | None, str]:
    """Run code in E2B sandbox and return a generated file.

    The code must write a file to ``/tmp/{output_filename}``.
    After execution we download that file from the sandbox.

    Args:
        code: Python source that produces a file.
        output_filename: Name of the file the code writes (e.g. ``report.xlsx``).
        language: Sandbox language identifier.
        timeout: Max execution seconds.
        install_deps: Extra pip packages to install before running.

    Returns:
        ``(file_bytes, stdout)`` — file_bytes is ``None`` when the file
        was not produced or an error occurred.
    """
    if not settings.e2b_api_key:
        return None, "E2B API key not configured"

    from e2b_code_interpreter import AsyncSandbox

    try:
        sandbox = await AsyncSandbox.create(api_key=settings.e2b_api_key)
    except Exception as e:
        logger.exception("Failed to create E2B sandbox")
        return None, f"Sandbox creation failed: {e}"

    try:
        # Install requested dependencies
        for dep in install_deps or []:
            logger.info("Installing dependency: %s", dep)
            await sandbox.run_code(f"!pip install -q {dep}", language="python", timeout=60)

        # Execute the code
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        execution = await sandbox.run_code(
            code,
            language=language,
            timeout=timeout,
            on_stdout=lambda out: stdout_parts.append(str(out)),
            on_stderr=lambda err: stderr_parts.append(str(err)),
        )

        stdout = "".join(stdout_parts)
        if execution.error:
            error_msg = str(execution.error)
            logger.warning("E2B execution error: %s", error_msg)
            return None, f"Code execution error: {error_msg}\nstderr: {''.join(stderr_parts)}"

        # Download the generated file
        file_path = f"/tmp/{output_filename}"
        try:
            file_bytes = await sandbox.files.read(file_path, format="bytes")
            return file_bytes, stdout
        except Exception as e:
            logger.warning("Could not read file %s from sandbox: %s", file_path, e)
            return None, f"File not found in sandbox: {file_path}\nstdout: {stdout}"

    except TimeoutError:
        return None, f"Execution timed out after {timeout}s"
    except Exception as e:
        logger.exception("E2B execution error")
        return None, str(e)
    finally:
        try:
            await sandbox.close()
        except Exception:
            pass
