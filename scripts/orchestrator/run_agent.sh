#!/bin/bash
# Run an agent (codex or gemini) in a worktree directory.
# Usage: run_agent.sh <agent> <worktree_path> <prompt> [model] [timeout]
set -euo pipefail

AGENT="$1"
WORKTREE_PATH="$2"
PROMPT="$3"
MODEL="${4:-}"
TIMEOUT="${5:-300}"
LOG_FILE="${WORKTREE_PATH}/.agent_output.log"

cd "$WORKTREE_PATH"

echo "[orchestrator] Running $AGENT in $WORKTREE_PATH" | tee "$LOG_FILE"
echo "[orchestrator] Model: ${MODEL:-default}" | tee -a "$LOG_FILE"
echo "[orchestrator] Timeout: ${TIMEOUT}s" | tee -a "$LOG_FILE"
echo "---" | tee -a "$LOG_FILE"

EXIT_CODE=0

if [ "$AGENT" = "codex" ]; then
    # Codex exec mode with Windows sandbox support
    CODEX_ARGS=(exec --enable experimental_windows_sandbox --json)
    if [ -n "$MODEL" ]; then
        CODEX_ARGS+=(-c "model=\"$MODEL\"")
    fi

    timeout "$TIMEOUT" codex "${CODEX_ARGS[@]}" "$PROMPT" \
        2>&1 | tee -a "$LOG_FILE" || EXIT_CODE=$?

elif [ "$AGENT" = "gemini" ]; then
    # Gemini non-interactive mode with auto-approve
    GEMINI_ARGS=(--approval-mode yolo -p "$PROMPT")
    if [ -n "$MODEL" ]; then
        GEMINI_ARGS=(-m "$MODEL" "${GEMINI_ARGS[@]}")
    fi

    timeout "$TIMEOUT" gemini "${GEMINI_ARGS[@]}" \
        2>&1 | tee -a "$LOG_FILE" || EXIT_CODE=$?

else
    echo "[orchestrator] Unknown agent: $AGENT" | tee -a "$LOG_FILE"
    exit 1
fi

echo "---" | tee -a "$LOG_FILE"
echo "[orchestrator] Agent exit code: $EXIT_CODE" | tee -a "$LOG_FILE"

# Check if agent made any changes (new files or modified files)
UNTRACKED=$(git ls-files --others --exclude-standard)
if git diff --quiet && git diff --cached --quiet && [ -z "$UNTRACKED" ]; then
    echo "[orchestrator] Agent produced no file changes" | tee -a "$LOG_FILE"
    exit 0
fi

# Stage and commit changes
git add -A
COMMIT_MSG="agent($AGENT): $(echo "$PROMPT" | head -c 72)"
git commit -m "$COMMIT_MSG" --no-verify 2>&1 | tee -a "$LOG_FILE" || true

echo "[orchestrator] Agent $AGENT finished" | tee -a "$LOG_FILE"
exit $EXIT_CODE
