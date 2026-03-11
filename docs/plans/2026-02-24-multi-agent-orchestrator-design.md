# Multi-Agent Orchestrator Design

**Date:** 2026-02-24
**Status:** ✅ DONE (2026-03-10) — supervisor routing, skill_catalog.yaml, detect_intent_v2 реализованы

## Overview

Claude Code acts as orchestrator, dispatching tasks to Codex CLI and Gemini CLI agents
working in isolated git worktrees. Claude Code + its sub-agents do the main work;
Codex/Gemini handle parallel/routine tasks for speed.

## Decisions

- **Autonomy:** Auto with restrictions — agents can edit files, no destructive ops. Claude reviews diff, runs lint+tests, merges automatically.
- **Routing:** Smart routing by default, user can override with `@codex`/`@gemini`, parallel mode available.
- **Worktrees:** `D:\Программы\Finance bot_worktrees\{agent}-{slug}-{timestamp}\`
- **Review:** Auto — lint + tests pass → merge. Fail → 1 retry to agent, then Claude fixes.
- **Config:** Minimal YAML file for paths, routing rules, agent commands.

## Routing Rules

| Task Type | Agent | Reason |
|-----------|-------|--------|
| Main work, architecture, features | Claude Code (self) | Best autonomous correctness |
| Write tests | Codex | Well-defined, pattern-based |
| Bulk refactor | Codex | Tedious but clear scope |
| Code review | Codex | Catches edge-cases |
| UI/frontend prototype | Gemini | Fast, 1M context |
| Research/analyze codebase | Gemini | Large context window |
| Generate docs/specs | Gemini | Good at text generation |
| Critical code | Both parallel | Best result from two |

## Task Lifecycle

```
CREATE   → git worktree add + new branch
PREPARE  → copy AGENTS.md/GEMINI.md into worktree
EXECUTE  → run CLI agent with prompt
VERIFY   → ruff check + pytest
REVIEW   → analyze diff
FIX      → retry agent (max 1) or fix self
MERGE    → git merge into current branch
CLEANUP  → git worktree remove
REPORT   → summary to user
```

## File Structure

```
scripts/orchestrator/
  config.yaml      — agent paths, routing, review settings
  orchestrate.py   — main entry: routing + worktree + merge
  routing.py       — task→agent routing logic
  review.py        — lint + test + diff analysis
  run_agent.sh     — shell wrapper for agent execution
AGENTS.md          — instructions for Codex CLI
GEMINI.md          — instructions for Gemini CLI
```

## CLI Interface

```bash
python scripts/orchestrator/orchestrate.py \
  --agent codex|gemini|both \
  --task write_tests|bulk_refactor|code_review|ui_prototype|... \
  --prompt "concrete task description" \
  --base-branch main \
  --files src/skills/foo/ \
  --timeout 300
```

## Output Format (JSON)

```json
{
  "status": "merged|failed|retry_exhausted",
  "agent": "codex|gemini",
  "branch": "agent/codex-write-tests-20260224-152030",
  "duration_sec": 45,
  "files_changed": ["tests/test_skills/test_foo.py"],
  "lint": "pass|fail",
  "tests": "pass (3 passed)|fail (1 failed)",
  "diff_summary": "+89 -0 in 1 file",
  "log_file": "path/to/log"
}
```
