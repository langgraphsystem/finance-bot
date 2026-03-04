#!/usr/bin/env python3
"""Multi-agent orchestrator — dispatches tasks to Codex/Gemini CLI in git worktrees.

Usage:
    python scripts/orchestrator/orchestrate.py \
        --agent codex|gemini|both \
        --task write_tests \
        --prompt "Write tests for src/skills/export_csv/handler.py" \
        --base-branch main

    # Auto-route based on prompt keywords:
    python scripts/orchestrator/orchestrate.py \
        --prompt "Write tests for the new export skill"

    # Parallel execution:
    python scripts/orchestrator/orchestrate.py \
        --agent both \
        --prompt "Implement retry logic in src/core/llm/router.py"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import our modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import yaml  # noqa: E402
from review import format_report, review_worktree  # noqa: E402
from routing import route_task  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Worktree management
# ---------------------------------------------------------------------------


def resolve_worktree_base(config: dict) -> Path:
    """Resolve worktree base directory (relative to project root or absolute)."""
    raw = config["worktrees"]["base_dir"]
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / raw
    return p.resolve()


def create_worktree(agent: str, slug: str, base_branch: str, config: dict) -> tuple[Path, str]:
    """Create a git worktree and return (path, branch_name)."""
    base_dir = resolve_worktree_base(config)
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = config["worktrees"].get("branch_prefix", "agent/")
    branch_name = f"{prefix}{agent}-{slug}-{timestamp}"
    worktree_dir = base_dir / f"{agent}-{slug}-{timestamp}"

    # Create worktree with new branch from base
    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_dir), base_branch],
        cwd=str(PROJECT_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )

    # Copy agent instructions file into worktree
    instructions_file = config["agents"][agent].get("instructions_file", "")
    if instructions_file:
        src = PROJECT_ROOT / instructions_file
        if src.exists():
            shutil.copy2(str(src), str(worktree_dir / instructions_file))

    return worktree_dir, branch_name


def cleanup_worktree(worktree_dir: Path) -> None:
    """Remove a git worktree."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        # Fallback: manual cleanup
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=10,
            )
            if worktree_dir.exists():
                shutil.rmtree(str(worktree_dir), ignore_errors=True)
        except Exception:
            pass


def delete_branch(branch_name: str) -> None:
    """Delete a local branch after merge."""
    try:
        subprocess.run(
            ["git", "branch", "-d", branch_name],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 30) -> str:
    """Create a short slug from a prompt for branch/dir naming."""
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _build_agent_cmd(agent: str, prompt: str, config: dict, model: str | None) -> list[str]:
    """Build the CLI command for an agent."""
    if agent == "codex":
        cmd = ["codex", "exec", "--enable", "experimental_windows_sandbox", "--json"]
        effective_model = model or config["agents"]["codex"].get("model")
        if effective_model:
            cmd.extend(["-c", f'model="{effective_model}"'])
        cmd.append(prompt)
        return cmd

    elif agent == "gemini":
        cmd = ["gemini", "--approval-mode", "yolo"]
        effective_model = model or config["agents"]["gemini"].get("model")
        if effective_model:
            cmd.extend(["-m", effective_model])
        cmd.extend(["-p", prompt])
        return cmd

    raise ValueError(f"Unknown agent: {agent}")


async def run_agent(
    agent: str,
    prompt: str,
    worktree_dir: Path,
    config: dict,
    model: str | None = None,
) -> tuple[int, str]:
    """Run a CLI agent in the worktree directory.

    Uses subprocess.Popen in a thread (not asyncio.create_subprocess_exec)
    because on Windows the CLI tools are .cmd wrappers that need shell=True.
    """
    agent_cfg = config["agents"][agent]
    timeout_sec = agent_cfg.get("timeout", 300)
    log_file = worktree_dir / ".agent_output.log"

    cmd = _build_agent_cmd(agent, prompt, config, model)
    # Join into shell command string (needed for Windows .cmd wrappers)
    shell_cmd = subprocess.list2cmdline(cmd)

    print(f"[orchestrator] Running: {shell_cmd[:120]}...", file=sys.stderr)

    def _run_blocking() -> tuple[int, str]:
        try:
            result = subprocess.run(
                shell_cmd,
                shell=True,
                cwd=str(worktree_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            output = result.stdout + result.stderr
            log_file.write_text(output, encoding="utf-8")
            return result.returncode, output
        except subprocess.TimeoutExpired:
            msg = f"[orchestrator] Agent timed out after {timeout_sec}s"
            log_file.write_text(msg, encoding="utf-8")
            return 124, msg
        except Exception as e:
            msg = f"[orchestrator] Agent execution error: {e}"
            log_file.write_text(msg, encoding="utf-8")
            return 1, msg

    loop = asyncio.get_event_loop()
    returncode, output = await loop.run_in_executor(None, _run_blocking)

    # Auto-commit any changes the agent made
    await _commit_agent_changes(agent, prompt, worktree_dir)

    return returncode, str(log_file)


async def _commit_agent_changes(agent: str, prompt: str, worktree_dir: Path) -> None:
    """Stage and commit any changes the agent made in the worktree."""
    cwd = str(worktree_dir)

    # Check for any changes (modified or untracked)
    diff_proc = subprocess.run(
        ["git", "diff", "--quiet"], cwd=cwd, capture_output=True
    )
    cached_proc = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=cwd, capture_output=True
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd, capture_output=True, text=True,
    )

    has_changes = (
        diff_proc.returncode != 0
        or cached_proc.returncode != 0
        or bool(untracked.stdout.strip())
    )

    if not has_changes:
        return

    # Stage and commit
    subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
    msg = f"agent({agent}): {prompt[:72]}"
    subprocess.run(
        ["git", "commit", "-m", msg, "--no-verify"],
        cwd=cwd, capture_output=True, text=True,
    )


async def run_single_agent(
    agent: str,
    prompt: str,
    task_type: str | None,
    base_branch: str,
    config: dict,
    model: str | None = None,
) -> str:
    """Full lifecycle for a single agent: create worktree → run → review → merge/fail."""
    slug = slugify(prompt)
    worktree_dir, branch_name = create_worktree(agent, slug, base_branch, config)

    # Persistent log dir (survives worktree cleanup)
    logs_dir = resolve_worktree_base(config) / ".logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    persistent_log = str(logs_dir / f"{agent}-{slug}-{datetime.now():%Y%m%d-%H%M%S}.log")

    status = "failed"
    try:
        start = time.time()

        # Run agent
        exit_code, log_file = await run_agent(agent, prompt, worktree_dir, config, model)
        duration = time.time() - start

        # Copy log to persistent location
        wt_log = worktree_dir / ".agent_output.log"
        if wt_log.exists():
            shutil.copy2(str(wt_log), persistent_log)

        # Review
        review_cfg = config.get("review", {})
        result = review_worktree(
            worktree_path=str(worktree_dir),
            branch=branch_name,
            base_branch=base_branch,
            lint_cmd=review_cfg.get("lint_cmd", "ruff check src/ tests/"),
            test_cmd=review_cfg.get("test_cmd", "pytest tests/ -x -q --tb=short"),
            retry_count=0,
            max_retries=config["agents"][agent].get("max_retries", 1),
        )

        # Retry if needed
        if result.action == "retry":
            retry_prompt = (
                f"Your previous attempt had errors. Fix ONLY the files you created/modified — "
                f"do NOT touch any other files in the project.\n\n"
                f"Errors:\n{result.errors}\n\n"
                f"Original task: {prompt}"
            )
            exit_code, log_file = await run_agent(
                agent, retry_prompt, worktree_dir, config, model
            )
            duration = time.time() - start

            # Update persistent log with retry output
            if wt_log.exists():
                with open(persistent_log, "a", encoding="utf-8") as f:
                    f.write("\n\n=== RETRY ===\n\n")
                    f.write(wt_log.read_text(encoding="utf-8"))

            result = review_worktree(
                worktree_path=str(worktree_dir),
                branch=branch_name,
                base_branch=base_branch,
                lint_cmd=review_cfg.get("lint_cmd", "ruff check src/ tests/"),
                test_cmd=review_cfg.get("test_cmd", "pytest tests/ -x -q --tb=short"),
                retry_count=1,
                max_retries=1,
            )

        # Merge if passed
        if result.passed and review_cfg.get("auto_merge", True):
            merge_result = subprocess.run(
                ["git", "merge", branch_name, "--no-ff", "-m",
                 f"Merge {agent} work: {slug}"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            if merge_result.returncode == 0:
                status = "merged"
            else:
                status = "merge_conflict"
                result.errors = merge_result.stderr
        elif result.passed:
            status = "reviewed_ok"

        report = format_report(agent, status, branch_name, duration, result, persistent_log)
        return report

    finally:
        # Cleanup worktree (logs survive in persistent location)
        if config["worktrees"].get("auto_cleanup", True):
            cleanup_worktree(worktree_dir)
            if status == "merged":
                delete_branch(branch_name)


async def run_both_agents(
    prompt: str,
    task_type: str | None,
    base_branch: str,
    config: dict,
) -> str:
    """Run both agents in parallel, pick the best result."""
    codex_task = asyncio.create_task(
        run_single_agent("codex", prompt, task_type, base_branch, config)
    )
    gemini_task = asyncio.create_task(
        run_single_agent("gemini", prompt, task_type, base_branch, config)
    )

    codex_report, gemini_report = await asyncio.gather(
        codex_task, gemini_task, return_exceptions=True
    )

    # Parse results
    results = {}
    for name, report in [("codex", codex_report), ("gemini", gemini_report)]:
        if isinstance(report, Exception):
            results[name] = {"status": "error", "error": str(report)}
        else:
            try:
                results[name] = json.loads(report)
            except (json.JSONDecodeError, TypeError):
                results[name] = {"status": "error", "error": str(report)}

    # Pick best: merged > reviewed_ok > failed
    priority = {"merged": 3, "reviewed_ok": 2, "merge_conflict": 1, "failed": 0, "error": -1}

    codex_score = priority.get(results["codex"].get("status", "error"), -1)
    gemini_score = priority.get(results["gemini"].get("status", "error"), -1)

    winner = "codex" if codex_score >= gemini_score else "gemini"

    combined = {
        "mode": "parallel",
        "winner": winner,
        "codex": results["codex"],
        "gemini": results["gemini"],
    }
    return json.dumps(combined, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-agent orchestrator — dispatch tasks to Codex/Gemini CLI"
    )
    parser.add_argument(
        "--agent",
        choices=["codex", "gemini", "both"],
        help="Which agent to use (default: auto-route based on task/prompt)",
    )
    parser.add_argument("--task", help="Task type for routing (write_tests, bulk_refactor, etc.)")
    parser.add_argument("--prompt", required=True, help="Task description for the agent")
    parser.add_argument("--base-branch", default="main", help="Base branch (default: main)")
    parser.add_argument("--model", help="Override model for the agent")
    parser.add_argument("--timeout", type=int, help="Override timeout in seconds")
    parser.add_argument(
        "--files", help="Scope: specific files/dirs the agent should focus on"
    )
    parser.add_argument(
        "--config",
        help="Path to config.yaml (default: scripts/orchestrator/config.yaml)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # Load config
    config_path = Path(args.config) if args.config else CONFIG_PATH
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Override timeout if specified
    if args.timeout:
        for agent_cfg in config["agents"].values():
            agent_cfg["timeout"] = args.timeout

    # Build full prompt with file scope
    prompt = args.prompt
    if args.files:
        prompt = f"{prompt}\n\nFocus on these files/directories: {args.files}"

    # Route
    routing = route_task(args.task, prompt, args.agent)
    agent = routing["agent"]
    model = args.model or routing.get("model")

    print(f"[orchestrator] Routing: {agent} — {routing.get('reason', 'n/a')}", file=sys.stderr)

    # Execute
    if agent == "both":
        report = await run_both_agents(prompt, args.task, args.base_branch, config)
    else:
        report = await run_single_agent(
            agent, prompt, args.task, args.base_branch, config, model
        )

    # Output JSON report to stdout
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
