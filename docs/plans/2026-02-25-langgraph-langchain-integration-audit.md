# LangGraph/LangChain Audit and Integration Plan

Date: 2026-02-25
Updated: 2026-02-26
Scope: Current use of LangGraph/LangChain in the project and practical integration points.

## 0. Implementation Status

| Priority | Task | Status |
|----------|------|--------|
| P1 | Booking FSM → LangGraph | **DONE** (`a5e2748`) |
| P2 | Pending actions → interrupt HITL | **DONE** (`3a5df41`) |
| P3 | Brief fan-out/fan-in + caching | **DONE** (`3a5df41`) |
| P4 | Email HITL + checkpointer | **DONE** (`3a5df41`) |
| P5 | Expand orchestrators (booking) | **DONE** (`a5e2748`) |
| — | PostgreSQL checkpointer | **DONE** (`3a5df41`) |
| — | Node caching (Brief 60s) | **DONE** |
| — | Progressive Skill Loading | **DONE** |
| — | Supervisor routing module | **DONE** |
| — | Scoped intent detection (2-stage) | **DONE** |
| — | Pre/Post model hooks | **DONE** |
| — | Full supervisor integration | **DONE** |
| — | Finance Specialist domain routing | **DONE** (`f191faf`) |
| — | Checkpointer test fix (mock psycopg) | **DONE** (`f191faf`) |
| — | Dead code cleanup (hooks.py removed) | **DONE** (`f191faf`) |

## 1. Summary

Project already includes LangGraph dependencies and uses LangGraph in four orchestrators:

1. Email orchestrator (with HITL interrupt/resume).
2. Brief (morning/evening) orchestrator (parallel fan-out + node caching).
3. Approval orchestrator (replaces Redis pending_actions).
4. Booking orchestrator (FSM with interrupt-based HITL).

LangChain packages are installed but practically not used in the runtime code path.

## 2. Current State in Repository

## 2.1 Dependencies

From project manifests:

1. `langgraph>=1.0.8`
2. `langchain-anthropic>=0.3.0`

Resolved versions in `uv.lock` include:

1. `langgraph 1.0.8`
2. `langchain 1.2.10`
3. `langchain-core 1.2.11`
4. `langchain-anthropic 1.3.3`

## 2.2 Where LangGraph is already implemented

1. `src/orchestrators/email/graph.py`
2. `src/orchestrators/brief/graph.py`
3. Routing integration via `DomainRouter`:
   1. `Domain.email`
   2. `Domain.brief`
   3. Files: `src/core/router.py`, `src/core/domain_router.py`

## 2.3 What is not implemented yet (LangGraph feature gaps)

Current graphs compile and execute, but advanced LangGraph runtime features are not used:

1. No checkpointer/persistence layer for graph threads.
2. No interrupt/resume human-in-the-loop flow.
3. No time-travel/fork replay.
4. No subgraph composition.
5. No streaming graph updates to channel UX.

## 2.4 LangChain usage status

1. LangChain packages are present in environment.
2. Direct LangChain runtime abstractions (agents/runnables/middleware/store) are not used in `src/api/tests`.
3. Existing core logic uses custom skill router + DomainRouter + direct LLM clients.

## 3. Practical Integration Targets (Priority Order)

## P1: Browser and booking conversational FSM -> LangGraph

Current FSM-like flow in Redis can be migrated to graph state with persistence and human approval steps.

Primary files:

1. `src/tools/browser_booking.py`
2. `src/tools/browser_login.py`
3. `src/core/router.py`

Benefits:

1. Stable resume/retry behavior.
2. Cleaner state transitions and observability.
3. Easier support for multi-step transactional actions.

## P2: Pending actions confirmation -> Interrupt-based HITL

Replace manual `pending_action:*` Redis flow with graph interrupts and controlled resume.

Primary file:

1. `src/core/pending_actions.py`

Benefits:

1. Unified approval model for send/create/delete side effects.
2. Lower logic duplication in router callbacks.

## P3: Brief orchestrator hardening

Bring brief graph in line with intended fan-out/fan-in model and add optional streaming updates.

Primary files:

1. `src/orchestrators/brief/graph.py`
2. `src/orchestrators/brief/nodes.py`

Benefits:

1. Actual parallel domain collection.
2. Lower latency for morning/evening responses.

## P4: Email orchestrator productionization

Move from scaffold behavior to full revision/send workflow with persisted state and HITL confirmations.

Primary files:

1. `src/orchestrators/email/graph.py`
2. `src/orchestrators/email/nodes.py`

Benefits:

1. Reliable compose/review/send loop.
2. Better failure recovery for mail operations.

## P5: Expand domain orchestrators beyond email/brief

Candidate domains for next orchestrators:

1. `booking`
2. `research`
3. `writing`

Integration entrypoint already exists in `DomainRouter`.

## 4. Recommended vNext Architecture for LangGraph Adoption

## 4.1 Principles

1. Keep existing skill path as fallback.
2. Add orchestrators domain-by-domain.
3. Enable advanced features behind flags.
4. Avoid large-bang migration.

## 4.2 Rollout Flags

Suggested feature flags:

1. `FF_LANGGRAPH_BOOKING_V1`
2. `FF_LANGGRAPH_PENDING_ACTIONS_V1`
3. `FF_LANGGRAPH_EMAIL_V2`
4. `FF_LANGGRAPH_BRIEF_PARALLEL_V2`

## 4.3 Minimal Technical Stack Additions

1. Graph checkpointer storage (Redis or Postgres-backed).
2. Standard graph state IDs per user/session/domain.
3. Unified telemetry for node transitions and interrupts.

## 5. Risks and Controls

1. Risk: workflow complexity and hidden state bugs.  
   Control: gradual rollout per domain + deterministic state tests.
2. Risk: latency increase in multi-node flows.  
   Control: node-level timeout budget and fast fallback path.
3. Risk: broken user interactions during migration.  
   Control: feature flags + legacy path kept active.

## 6. Delivery Plan (2-week practical scope)

Week 1:

1. Add checkpointer abstraction and telemetry.
2. Implement booking graph MVP behind flag.
3. Add tests for resume/timeout/fallback.

Week 2:

1. Move pending actions to interrupt/resume flow.
2. Harden brief graph fan-out/fan-in.
3. Expand email graph node logic and approval path.

## 7. Code References

1. `src/orchestrators/email/graph.py`
2. `src/orchestrators/email/nodes.py`
3. `src/orchestrators/brief/graph.py`
4. `src/orchestrators/brief/nodes.py`
5. `src/core/domain_router.py`
6. `src/core/router.py`
7. `src/tools/browser_booking.py`
8. `src/tools/browser_login.py`
9. `src/core/pending_actions.py`

## 8. Official Docs for Verification

1. https://docs.langchain.com/oss/python/langchain/overview
2. https://docs.langchain.com/oss/python/langgraph/persistence
3. https://docs.langchain.com/oss/python/langgraph/durable-execution
4. https://docs.langchain.com/oss/python/langgraph/interrupts
5. https://docs.langchain.com/oss/python/langgraph/use-subgraphs
6. https://docs.langchain.com/oss/python/langgraph/streaming
7. https://docs.langchain.com/oss/python/langchain/agents
8. https://docs.langchain.com/oss/python/langchain/middleware/overview
9. https://docs.langchain.com/oss/python/langchain/runtime

