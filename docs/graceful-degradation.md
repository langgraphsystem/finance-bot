# Graceful Degradation Policy

**Phase E — Memory & Personalization Improvement Plan**
**Date:** 2026-03-06

This document describes how the Finance Bot behaves when external services are unavailable.
The principle: **never show an error to the user if a fallback exists**.

---

## Redis

**Used for:** identity cache, session buffer, undo window, DLQ, suggestions cooldown, rate limiter, LangGraph checkpointer.

| Scenario | Behavior |
|----------|----------|
| Redis down at startup | App starts normally; Redis-dependent features degrade silently |
| `get_core_identity()` — Redis miss | Falls through to PostgreSQL; response is slower but correct |
| `update_core_identity()` — Redis unavailable | DB write succeeds; cache invalidation skipped (stale TTL expires in 10 min) |
| `store_undo()` fails | Undo button not shown; no user-visible error |
| `session_buffer` write fails | Logged at DEBUG; session context loaded from Mem0 instead |
| Rate limiter Redis error | Fails open — request is allowed through |
| DLQ enqueue fails | Logged at ERROR; memory fact is lost (acceptable — non-critical path) |

**Recovery:** Redis auto-reconnects; no manual intervention needed.

---

## Mem0 (pgvector)

**Used for:** long-term fact storage, semantic search, memory_show/forget/save.

| Scenario | Behavior |
|----------|----------|
| Mem0 `add_memory()` fails | Fact enqueued to Redis DLQ (`mem0_dlq:{user_id}`); retried every 5 min by Taskiq cron |
| Circuit breaker OPEN (3 failures) | All Mem0 ops short-circuited; failed writes go to DLQ; reads return `[]` |
| `search_memories()` fails | Returns empty list; context assembled without Mem0 memories |
| Circuit OPEN → recovery | After 30s recovery timeout, HALF_OPEN probe; closes on success |
| DLQ > 200 items | Warning log triggered; no automatic purge |

**Circuit breaker:** `circuits["mem0"]` — threshold 3 failures, 30s recovery.

---

## Supabase / PostgreSQL

**Used for:** all persistent data (transactions, tasks, identity, rules, summaries).

| Scenario | Behavior |
|----------|----------|
| Slow DB (timeout) | `async_session` times out; skill returns error message to user |
| `get_core_identity()` DB error | Returns `_EMPTY_IDENTITY = {}`; bot works without personalization |
| `_ensure_user_profile()` fails | Identity update skipped; logged at WARNING |
| `get_user_rules()` fails | Returns `[]`; no rules injected; context assembled without rules |
| Read-only replica lag | Not applicable — single Supabase instance |

**Note:** PostgreSQL failures surface to the user as skill errors. There is no silent fallback for DB writes — data integrity requires explicit failure reporting.

---

## LLM Providers

**Used for:** intent detection (Gemini primary → Claude fallback), skill execution, guardrails.

| Scenario | Behavior |
|----------|----------|
| Gemini intent detection fails | Falls back to Claude Haiku (`_detect_with_claude`) |
| Claude fallback also fails | Returns `IntentDetectionResult(intent="general_chat", confidence=0.5)` |
| Guardrails LLM call fails | Fails open — message allowed through |
| Post-gen check LLM fails | Fails open — original response sent unchanged |
| Skill LLM call fails | Skill returns error SkillResult; user sees friendly error message |
| Rate limit (429) on Gemini summary | Falls back to Claude Haiku for summarization |

**Circuit breakers:** `circuits["anthropic"]`, `circuits["openai"]`, `circuits["google"]` — threshold 3 failures, 60s recovery.

---

## Taskiq Worker

**Used for:** async Mem0 updates, merchant mapping, budget checks, DLQ retry, reminder dispatch.

| Scenario | Behavior |
|----------|----------|
| Worker process down | Background tasks queue up in Redis broker; processed when worker restarts |
| `async_mem0_update` task fails | Facts lost if DLQ also unavailable; otherwise enqueued for retry |
| `async_mem0_dlq_retry` cron skipped | DLQ accumulates; retried on next 5-min tick |
| Budget check task fails | No alert sent; non-critical |

**Note:** Worker is a separate Railway service. If it's down, all user-facing responses still work — only background enrichment is delayed.

---

## Summary: Failure Impact Matrix

| Service | User impact when DOWN | Data loss risk |
|---------|----------------------|---------------|
| Redis | Slightly slower responses; no undo; no suggestions | Low (cache only) |
| Mem0 | No long-term memory recall; DLQ accumulates | Low (DLQ retry) |
| PostgreSQL | Skill errors; data not saved | High |
| LLM (Gemini) | Automatic fallback to Claude | None |
| LLM (all) | Friendly error message | None |
| Taskiq worker | Background enrichment delayed | Low |

---

## Monitoring Signals

- **DLQ size > 200:** `logger.warning("Mem0 DLQ for user %s has %d items")` in `mem0_dlq.py`
- **Circuit OPEN:** logged at WARNING in `mem0_client.py`, `circuit_breaker.py`
- **Identity load failure:** logged at WARNING in `identity.py`
- **Health endpoint:** `GET /health/detailed` — includes circuit breaker states (requires `HEALTH_SECRET` header)
