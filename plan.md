# Deep Agents — Implementation Plan

## Overview

Add a LangGraph-based "Deep Agent" orchestrator for complex multi-step tasks. Applied **selectively** to 2 skills — the other 87+ skills remain untouched.

**Key principle**: Don't use the full Deep Agents SDK (20x token overhead). Instead, build a lightweight LangGraph graph that borrows the best ideas: planning, iterative execution, context management.

## Architecture

```
Skill handler (generate_program / tax_estimate)
  │
  ├─ Simple request → current path (single LLM call, ~4K tokens, 5 sec)
  │   e.g. "hello world script", "Q1 tax estimate"
  │
  └─ Complex request → Deep Agent Orchestrator (LangGraph graph, ~50-150K tokens, 60-180 sec)
      e.g. "CRM with auth + dashboard", "full annual tax report with deductions analysis"
      │
      ├── plan_task        → Opus creates a step-by-step plan (3-8 steps)
      ├── execute_step     → Sonnet executes each step (code gen / data collection)
      ├── validate_step    → E2B runs code / validates output
      ├── review_and_fix   → If error: analyze + targeted fix (max 2 retries per step)
      └── finalize         → Assemble final result (URL / PDF / document)
```

## Step-by-step Plan

### Step 1: Create complexity classifier (`src/core/deep_agent/classifier.py`)

Determines whether a request needs the deep agent path.

```python
class ComplexityLevel(StrEnum):
    simple = "simple"
    complex = "complex"

async def classify_complexity(description: str, skill_type: str) -> ComplexityLevel
```

For `generate_program`:
- **Complex signals**: multi-page, auth, database, API integration, dashboard, CRUD, multiple routes, admin panel, deployment
- **Simple signals**: single function, hello world, calculator, converter, script, one-page

For `tax_estimate`:
- **Complex signals**: annual, full report, deductions analysis, Schedule C, multi-quarter, comparison
- **Simple signals**: current quarter, estimate, how much

Uses keyword matching first (zero LLM cost). Falls back to a quick Haiku classification only if ambiguous.

### Step 2: Create Deep Agent state (`src/orchestrators/deep_agent/state.py`)

```python
class DeepAgentState(TypedDict, total=False):
    # Identity
    user_id: str
    family_id: str
    language: str

    # Task
    task_description: str
    skill_type: str          # "generate_program" | "tax_report"

    # Planning
    plan: list[dict]         # [{step: str, status: "pending"|"done"|"failed", output: str}]
    current_step_index: int

    # Execution context
    files: dict[str, str]    # virtual filesystem: {filename: content}
    step_outputs: list[str]  # outputs from each step

    # Code generation specific
    model: str
    ext: str
    filename: str

    # Tax report specific
    financial_data: dict

    # Error handling
    error: str
    retry_count: int
    max_retries: int         # 2 per step

    # Output
    response_text: str
    buttons: list[dict]
    document: bytes | None
    document_name: str
```

### Step 3: Create Deep Agent nodes (`src/orchestrators/deep_agent/nodes.py`)

4 core nodes:

1. **`plan_task`** — Uses Opus to create a structured plan (3-8 steps). Returns plan as list of step dicts.
   - For generate_program: architecture sketch → file structure → core logic → routes/UI → tests → integration
   - For tax_report: data collection → categorization → deduction analysis → tax calculation → report generation → PDF

2. **`execute_step`** — Uses Sonnet to execute current step. Writes output to `files` dict (virtual FS).
   - For code: generates code for the current step, appending to the accumulated codebase
   - For tax: queries DB, processes data, builds report sections

3. **`validate_step`** — Runs validation:
   - For code: E2B execution, check for errors
   - For tax: sanity check numbers (no negative tax, amounts match)

4. **`review_and_fix`** — On failure: analyzes error, applies targeted fix (not full regeneration). Max 2 retries per step. If exhausted, marks step as failed and continues.

5. **`finalize`** — Assembles final output:
   - For code: saves to Redis, runs in E2B, returns URL + Code button
   - For tax: formats report, generates PDF if requested

Routing logic:
```
plan_task → execute_step → validate_step
    ↑              ↑             │
    │              │     ┌───────┴────────┐
    │              │     │ success        │ error
    │              │     ↓                ↓
    │              │  [next step?]    review_and_fix
    │              │     │ yes           │
    │              │     └───────────────┘
    │              │     │ no (all done)
    │              │     ↓
    │              │  finalize → END
```

### Step 4: Create Deep Agent graph (`src/orchestrators/deep_agent/graph.py`)

Build the LangGraph StateGraph with checkpointer. Create `DeepAgentOrchestrator` class following `Orchestrator` protocol.

The orchestrator is NOT registered in DomainRouter (it's called directly from skill handlers, not from the intent routing layer).

### Step 5: Modify `generate_program` handler

In `src/skills/generate_program/handler.py`:
- Import classifier and orchestrator
- In `execute()`: classify complexity first
- If simple → current path (unchanged)
- If complex → call `DeepAgentOrchestrator.run()` with description + language
- Keep all existing helper functions and tests passing

### Step 6: Modify `tax_estimate` handler

In `src/skills/tax_estimate/handler.py`:
- Import classifier and orchestrator
- In `execute()`: classify complexity
- If simple → current path (unchanged)
- If complex → call `DeepAgentOrchestrator.run()` with financial data context
- Existing tests remain green

### Step 7: Add feature flag

In `src/core/config.py` — add `ff_deep_agents: bool = False`
Both skills check the flag before routing to deep agent path. Default OFF for safe rollout.

### Step 8: Tests

New test files:
- `tests/test_orchestrators/test_deep_agent.py` — graph construction, node logic, routing
- `tests/test_skills/test_generate_program_deep.py` — complex classification + deep path
- `tests/test_skills/test_tax_estimate_deep.py` — complex classification + deep path

Test approach: mock LLM calls + E2B + DB. Verify:
- Classifier correctly identifies simple vs complex
- Plan node produces valid plan structure
- Execute node populates files dict
- Validate node catches errors
- Review node applies fixes
- Finalize node produces correct SkillResult
- Feature flag gates the deep path
- Simple requests still use the fast path (regression)

### Step 9: Update config/skill_catalog.yaml

Add `deep_agent` complexity annotations to relevant skills.

### Step 10: Run lint + tests

```bash
ruff check src/ tests/
ruff format src/ tests/
pytest tests/ -x -q --tb=short
```

## Files to Create

| File | Purpose |
|------|---------|
| `src/core/deep_agent/__init__.py` | Package init |
| `src/core/deep_agent/classifier.py` | Complexity classifier |
| `src/orchestrators/deep_agent/__init__.py` | Package init |
| `src/orchestrators/deep_agent/state.py` | DeepAgentState TypedDict |
| `src/orchestrators/deep_agent/nodes.py` | Graph nodes (plan, execute, validate, review, finalize) |
| `src/orchestrators/deep_agent/graph.py` | StateGraph + DeepAgentOrchestrator class |
| `tests/test_orchestrators/test_deep_agent.py` | Orchestrator tests |
| `tests/test_skills/test_generate_program_deep.py` | Deep path tests for generate_program |
| `tests/test_skills/test_tax_estimate_deep.py` | Deep path tests for tax_estimate |

## Files to Modify

| File | Change |
|------|--------|
| `src/core/config.py` | Add `ff_deep_agents` feature flag |
| `src/skills/generate_program/handler.py` | Add complexity gate → deep agent path |
| `src/skills/tax_estimate/handler.py` | Add complexity gate → deep agent path |

## What We're NOT Doing

- Not installing Deep Agents SDK (saves 20x token overhead)
- Not touching other 87+ skills
- Not adding new intents or domains
- Not changing the intent detection pipeline
- Not adding new DB tables
- Not modifying DomainRouter (deep agent is invoked directly from skill handlers)
