# Deep Agents: Ship Plan

**Date:** 2026-03-01
**PRD:** `docs/prds/deep-agents.md`
**Branch:** `claude/plan-review-Aj1Y7`
**Status:** Planning

---

## Current State

The Deep Agent infrastructure is **fully built and tested** but disabled:

```
ff_deep_agents = False  (src/core/config.py:125)
```

### Existing Code (no changes needed)

| File | What it does |
|------|-------------|
| `src/core/deep_agent/classifier.py` | Keyword classifier: simple vs complex (zero LLM) |
| `src/orchestrators/deep_agent/graph.py` | 6-node LangGraph StateGraph with checkpointer |
| `src/orchestrators/deep_agent/nodes.py` | plan_task, execute_step, validate_step, review_and_fix, finalize |
| `src/orchestrators/deep_agent/state.py` | DeepAgentState TypedDict |
| `src/skills/generate_program/handler.py:262-276` | Complexity gate + `_execute_deep()` |
| `src/skills/tax_estimate/handler.py:80-93` | Complexity gate + `_execute_deep()` |
| `tests/test_orchestrators/test_deep_agent.py` | 415 lines — classifier, routing, nodes |
| `tests/test_skills/test_generate_program_deep.py` | 206 lines — flag on/off paths |
| `tests/test_skills/test_tax_estimate_deep.py` | 247 lines — flag on/off paths |

---

## Implementation Steps

### Step 1: Progress Feedback

**Problem:** Deep agent takes 30-90 seconds. User sees nothing during this time.

**File:** `src/orchestrators/deep_agent/nodes.py`

**Changes:**
- Add `progress_callback` to `DeepAgentState` (optional callable)
- In `plan_task`: emit "Planning your app — {N} steps"
- In `execute_step`: emit "Step {i}/{N}: {step_description}..."
- In `review_and_fix`: emit "Fixing an issue in step {i}..."

**File:** `src/skills/generate_program/handler.py` (`_execute_deep`)

**Changes:**
- Pass a progress callback that sends typing indicator + status via gateway
- Use `context.gateway.send_typing()` + `context.gateway.send_message()` for interim updates

**File:** `src/orchestrators/deep_agent/state.py`

**Changes:**
- Add `progress_messages: list[str]` to state for logging

### Step 2: Usage Limits

**Problem:** Deep agent costs ~$0.39/request. Unlimited use breaks economics.

**File:** `src/skills/generate_program/handler.py`

**Changes:**
- Before `_execute_deep()`, check Redis counter `deep_agent:daily:{user_id}`
- Default limit: 3/day (configurable via settings)
- If exceeded: return "You've hit your daily limit for complex builds (3/3). Simple requests still work. Resets at midnight."
- After successful deep agent run: increment counter with TTL = seconds until midnight

**File:** `src/skills/tax_estimate/handler.py`

**Changes:**
- Same daily limit check before `_execute_deep()`
- Shared counter — code gen and tax reports count together

**File:** `src/core/config.py`

**Changes:**
- Add `deep_agent_daily_limit: int = 3`

### Step 3: Cost Tracking

**Problem:** Need to monitor token spend per deep agent request.

**File:** `src/orchestrators/deep_agent/nodes.py`

**Changes:**
- Add `total_tokens: int` to state
- After each `generate_text()` call, increment token count (estimated from response length)
- In `finalize`: log total tokens to Langfuse via `@observe` metadata

No new files needed — Langfuse `@observe` decorators already exist on every node.

### Step 4: Plan Step Visibility in Response

**Problem:** User sees "Plan: 5/5 steps completed" but not what the steps were.

**File:** `src/orchestrators/deep_agent/nodes.py` (`_finalize_code`)

**Changes:**
- Build a step summary list:
  ```
  1. Set up Flask app with base HTML ✓
  2. Add user authentication ✓
  3. Create dashboard layout ✓
  4. Add payment tracking ✗ (auto-fixed)
  5. Integrate all components ✓
  ```
- Append to response_text (collapsed, max 8 lines)

### Step 5: E2E Integration Test

**File:** `tests/test_orchestrators/test_deep_agent_e2e.py` (new)

**Tests:**
1. Full graph run with mock LLM: plan → 3 steps → validate → finalize → SkillResult with URL
2. Graph run where step 2 fails → review_and_fix → succeeds on retry
3. Graph run where all steps fail → graceful degradation with error message
4. Tax report graph run → 4 sections assembled → disclaimer present
5. Timeout scenario → partial result returned

All LLM calls mocked. E2B calls mocked. Redis mocked.

### Step 6: Classifier Edge Cases

**File:** `tests/test_orchestrators/test_deep_agent.py`

**New tests:**
- "simple dashboard" → simple (simple keyword wins)
- Long description (300 chars) with no complex keywords → simple
- Russian complex request: "создай CRM с авторизацией и базой данных" → complex
- Mixed: "todo list with auth" → complex (auth is complex signal)
- Empty description → simple (default)

### Step 7: Enable Feature Flag

**File:** `src/core/config.py`

**Change:**
```python
ff_deep_agents: bool = True  # was False
```

This is the final step — only after all tests pass and hardening is verified.

---

## File Change Summary

| File | Change Type | Size |
|------|------------|------|
| `src/orchestrators/deep_agent/nodes.py` | Edit | ~40 lines (progress + cost tracking + step visibility) |
| `src/orchestrators/deep_agent/state.py` | Edit | ~3 lines (new state fields) |
| `src/skills/generate_program/handler.py` | Edit | ~15 lines (usage limit check) |
| `src/skills/tax_estimate/handler.py` | Edit | ~15 lines (usage limit check) |
| `src/core/config.py` | Edit | ~2 lines (new setting + flag flip) |
| `tests/test_orchestrators/test_deep_agent_e2e.py` | New | ~200 lines |
| `tests/test_orchestrators/test_deep_agent.py` | Edit | ~30 lines (new classifier tests) |
| **Total** | | **~305 lines** |

---

## Verification Plan

1. `ruff check src/ api/ tests/` — no lint errors
2. `ruff format src/ api/ tests/` — no formatting issues
3. `pytest tests/test_orchestrators/test_deep_agent.py -v` — all classifier + routing tests pass
4. `pytest tests/test_orchestrators/test_deep_agent_e2e.py -v` — all E2E tests pass
5. `pytest tests/test_skills/test_generate_program_deep.py -v` — flag on/off paths work
6. `pytest tests/test_skills/test_tax_estimate_deep.py -v` — flag on/off paths work
7. `pytest tests/ -x -q --tb=short` — full suite green

---

## Rollback Plan

If issues appear after enabling:
1. Set `FF_DEEP_AGENTS=false` in Railway env vars
2. Deploy — immediate rollback, zero code changes
3. All complex requests fall back to single-shot path (existing, proven behavior)

---

## Not Changing

- `src/orchestrators/deep_agent/graph.py` — graph structure is correct as-is
- `src/core/deep_agent/classifier.py` — classifier logic works, adding tests only
- Intent detection — no new intents needed
- Agent config — no new agents
- Database — no migrations
- Skill registry — no new skills
