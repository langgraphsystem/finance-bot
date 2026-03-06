# Graceful Degradation Policy

How the bot behaves when infrastructure components are unavailable or slow.
Covers: Redis, Mem0/pgvector, Supabase (PostgreSQL), LLM providers.

---

## 1. Redis Down

| Layer | Normal | Degraded | Impact |
|-------|--------|----------|--------|
| Sliding window (history) | Redis `LRANGE` | PostgreSQL `conversation_messages` fallback (`sliding_window._fallback_from_postgres`) | +50-100ms latency, no data loss |
| Session buffer | Redis `GET` | Returns empty; facts unavailable until Redis recovers | Minor — Mem0 still has long-term facts |
| Rate limiter | Redis `INCR+EXPIRE` | Fail-open (allow request) | Users not rate-limited during outage |
| Undo window | Redis `GET/SET` | Returns `None`; "nothing to undo" | Undo unavailable for ~2 min after recovery |
| Identity cache | Redis `GET` | Falls through to PostgreSQL query | +20ms per request |
| Pending actions | Redis `GET/SET` | Confirmation buttons stop working | User must retry the command |
| Clarify state | Redis `GET` | Disambiguation expires immediately | User must retype the message |

**Recovery:** Automatic. Redis reconnects; rolling TTL resets on next message.

## 2. Mem0 Down (pgvector / psycopg errors)

| Component | Normal | Degraded | Impact |
|-----------|--------|----------|--------|
| `search_memories()` | Vector search | Circuit breaker opens after 3 failures; returns `[]` | Bot has no long-term memory for ~30s |
| `add_memory()` | Vector insert | Enqueues to DLQ (`mem0_dlq`) for retry every 5 min | Facts saved later, not lost |
| `get_all_memories()` | Full scan | Circuit breaker; returns `[]` | Memory Vault shows empty |
| `delete_memory()` | Vector delete | Silently fails; logged as ERROR | Stale fact remains until next successful call |

**Circuit breaker config:** `failure_threshold=3`, `recovery_timeout=30s`.
After 30s, one probe request is sent (HALF_OPEN). If it succeeds, circuit closes.

**DLQ retry:** Taskiq cron every 5 min, processes 20 users/batch, re-enqueues on failure.

**Key fix:** `prepare_threshold=0` in connection string prevents prepared statement
conflicts with PgBouncer (transaction mode). Without it, Mem0 is effectively broken.

## 3. Supabase / PostgreSQL Slow or Down

| Component | Normal | Degraded | Impact |
|-----------|--------|----------|--------|
| Context assembly | DB queries for stats, identity | Timeout after connection pool wait; layers return empty | Bot responds without analytics/identity |
| Message persistence | `_persist_message()` | Retries 2x with backoff; logs ERROR on final failure | Message in Redis but not PostgreSQL |
| Core identity | DB read + Redis cache | Cached for 10 min; cache invalidated on any update attempt (even failed) | Stale identity for up to 10 min |
| Transaction writes | Skill DB writes | Skill returns error to user | User sees error, retries |

**Connection pool:** `pool_size=10`, `max_overflow=20`, `statement_cache_size=0`.

## 4. LLM Provider Down

| Provider | Role | Fallback | Config |
|----------|------|----------|--------|
| Gemini 3.1 Flash Lite | Intent detection (primary) | Claude Haiku 4.5 | `intent.py:detect_intent()` |
| Claude Sonnet 4.6 | Analytics, writing, email | GPT-5.2 (partial) | `llm/router.py:TASK_MODEL_MAP` |
| OpenAI embeddings | Mem0 embeddings | None (Mem0 fails, DLQ catches) | — |
| Anthropic Haiku | Guardrails | Fail-open (allow message) | `guardrails.py:check_input()` |

**Circuit breakers:** Separate instances for `anthropic`, `openai`, `google` providers.

## 5. Taskiq / Worker Down

| Component | Normal | Degraded | Impact |
|-----------|--------|----------|--------|
| Background Mem0 updates | Taskiq `.kiq()` | Fire-and-forget; task lost if Redis/worker down | Mem0 not updated until next message |
| Cron tasks (budget alerts, digest) | Scheduler process | Tasks skip; run on next cycle | Delayed notifications |
| DLQ retry | Every 5 min | Stops; items stay in Redis DLQ (24h TTL) | Delayed memory persistence |

**Mitigation:** Critical identity updates run synchronously via `immediate_identity_update()`,
not via Taskiq, so they are not affected by worker downtime.

## 6. Context Assembly Under Pressure

When total context exceeds the 150K token budget, layers are dropped in order:

1. Mem0 non-core namespaces (life, tasks, research)
2. Session summary (compress, then drop)
3. SQL analytics (compress to 2K, then drop)
4. Old history messages (keep MIN_SLIDING_WINDOW=5)
5. Mem0 core (finance, core, contacts) — last resort
6. Remaining history — absolute last resort

**NEVER dropped:** System prompt, core identity, user rules, session buffer, user message.

## 7. Monitoring

| Signal | Where | Level |
|--------|-------|-------|
| Mem0 failures | `mem0_client.py` | ERROR |
| Circuit breaker state | `/health/detailed` | INFO |
| DLQ queue size > 200 | `mem0_dlq.py` | WARNING |
| Persist message failure | `router.py` | ERROR |
| Guardrails unavailable | `guardrails.py` | CRITICAL |
| Sliding window fallback | `sliding_window.py` | INFO |
