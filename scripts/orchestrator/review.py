"""Post-execution review — lint, test, diff analysis."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class ReviewResult:
    lint_ok: bool = False
    lint_output: str = ""
    tests_ok: bool = False
    tests_output: str = ""
    diff_summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    action: str = "fail"  # "merge" | "retry" | "fail"
    errors: str = ""

    @property
    def passed(self) -> bool:
        return self.lint_ok and self.tests_ok


def _run(cmd: str, cwd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a shell command, return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {cmd}"
    except Exception as e:
        return False, f"Command failed: {e}"


def review_worktree(
    worktree_path: str,
    branch: str,
    base_branch: str = "main",
    lint_cmd: str = "ruff check src/ tests/",
    test_cmd: str = "pytest tests/ -x -q --tb=short",
    retry_count: int = 0,
    max_retries: int = 1,
) -> ReviewResult:
    """Review agent's work in a worktree."""
    result = ReviewResult()

    # 1. Check what changed
    ok, diff = _run(f"git diff {base_branch}...{branch} --stat", cwd=worktree_path)
    result.diff_summary = diff

    ok, files = _run(f"git diff {base_branch}...{branch} --name-only", cwd=worktree_path)
    result.files_changed = [f for f in files.split("\n") if f.strip()] if ok else []

    if not result.files_changed:
        result.action = "fail"
        result.errors = "Agent produced no changes"
        return result

    # 2. Lint
    result.lint_ok, result.lint_output = _run(lint_cmd, cwd=worktree_path)

    # 3. Tests — only run if lint passes (no point running broken code)
    if result.lint_ok:
        # Try to run only relevant test files first
        test_files = [f for f in result.files_changed if f.startswith("tests/")]
        if test_files:
            specific_test_cmd = f"pytest {' '.join(test_files)} -x -q --tb=short"
            result.tests_ok, result.tests_output = _run(specific_test_cmd, cwd=worktree_path)
        else:
            # No test files changed — run full suite
            result.tests_ok, result.tests_output = _run(test_cmd, cwd=worktree_path, timeout=180)
    else:
        result.tests_ok = False
        result.tests_output = "Skipped — lint failed"

    # 4. Decide action
    if result.passed:
        result.action = "merge"
    elif retry_count < max_retries:
        result.action = "retry"
        result.errors = _collect_errors(result)
    else:
        result.action = "fail"
        result.errors = _collect_errors(result)

    return result


def _collect_errors(result: ReviewResult) -> str:
    """Collect error messages for retry prompt."""
    errors = []
    if not result.lint_ok:
        errors.append(f"Lint errors:\n{result.lint_output}")
    if not result.tests_ok:
        errors.append(f"Test failures:\n{result.tests_output}")
    return "\n\n".join(errors)


def format_report(
    agent: str,
    status: str,
    branch: str,
    duration_sec: float,
    review_result: ReviewResult,
    log_file: str = "",
) -> str:
    """Format JSON report for Claude Code to consume."""
    report = {
        "status": status,
        "agent": agent,
        "branch": branch,
        "duration_sec": round(duration_sec, 1),
        "files_changed": review_result.files_changed,
        "lint": "pass" if review_result.lint_ok else "fail",
        "tests": "pass" if review_result.tests_ok else "fail",
        "diff_summary": review_result.diff_summary,
        "log_file": log_file,
    }
    if review_result.errors:
        report["errors"] = review_result.errors
    return json.dumps(report, indent=2, ensure_ascii=False)
