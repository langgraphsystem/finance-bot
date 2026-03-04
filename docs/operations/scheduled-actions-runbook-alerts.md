# Scheduled Actions Runbook and Alerts (H3)

Date: 2026-03-04
Scope: `scheduled_actions`, `scheduled_action_runs`

## Alert Thresholds

1. Duplicate sends: `>5%` in last 60 minutes.
2. Run failures: `>10%` in last 60 minutes.
3. Dispatcher lag: oldest due active action delayed by `>5 minutes`.
4. Send failures: absolute count `>=10` in last 15 minutes.

## Scenario: High Failure Rate

1. Confirm failure spike by source:
   `SELECT error_code, COUNT(*) FROM scheduled_action_runs WHERE started_at >= NOW() - INTERVAL '60 minutes' AND status = 'failed' GROUP BY error_code ORDER BY COUNT(*) DESC;`
2. If dominant `error_code` is collector-related, disable unstable source in new schedules and reduce collector timeout blast radius.
3. If dominant `error_code` is transport-related (`send_failed`), switch to degraded delivery path and page gateway owner.
4. If failures persist for >30 minutes, temporarily disable `ff_scheduled_actions` and keep `ff_sia_synthesis` off.

## Scenario: Send Failures

1. Verify telegram send failures:
   `SELECT COUNT(*) FROM scheduled_action_runs WHERE started_at >= NOW() - INTERVAL '15 minutes' AND error_code = 'send_failed';`
2. Validate bot token and gateway connectivity.
3. Resume by re-enabling transport; do not replay all failed runs at once, throttle manual re-run.
4. Announce incident in ops channel with affected time window and recovery timestamp.

## Scenario: Queue Lag

1. Check lag:
   `SELECT EXTRACT(EPOCH FROM (NOW() - MIN(next_run_at)))::int AS lag_seconds FROM scheduled_actions WHERE status = 'active' AND next_run_at <= NOW();`
2. If lag exceeds 300 seconds:
   increase worker concurrency, confirm scheduler heartbeat, and inspect long-running collectors.
3. If lag exceeds 900 seconds:
   disable synthesis (`ff_sia_synthesis=False`) to reduce per-run latency until queue recovers.

## Scenario: Duplicate Sends

1. Detect duplicates by action/time slot:
   `SELECT scheduled_action_id, planned_run_at, COUNT(*) FROM scheduled_action_runs WHERE started_at >= NOW() - INTERVAL '60 minutes' GROUP BY scheduled_action_id, planned_run_at HAVING COUNT(*) > 1;`
2. Confirm uniqueness constraint health and IntegrityError handling logs.
3. If duplicates continue, reduce dispatcher replica count to 1 and investigate lock behavior (`FOR UPDATE SKIP LOCKED` path).
4. Backfill user communication for duplicate notifications if user-facing spam occurred.

## Monitoring Queries

### Duplicate send rate (60m)

```sql
WITH agg AS (
    SELECT
        COUNT(*) AS total_runs,
        COUNT(*) FILTER (WHERE dup_count > 1) AS duplicate_runs
    FROM (
        SELECT
            scheduled_action_id,
            planned_run_at,
            COUNT(*) AS dup_count
        FROM scheduled_action_runs
        WHERE started_at >= NOW() - INTERVAL '60 minutes'
        GROUP BY scheduled_action_id, planned_run_at
    ) x
)
SELECT
    total_runs,
    duplicate_runs,
    ROUND(duplicate_runs::numeric * 100 / NULLIF(total_runs, 0), 2) AS duplicate_pct
FROM agg;
```

### Failure rate (60m)

```sql
SELECT
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_runs,
    ROUND(
        COUNT(*) FILTER (WHERE status = 'failed')::numeric * 100 / NULLIF(COUNT(*), 0),
        2
    ) AS failure_pct
FROM scheduled_action_runs
WHERE started_at >= NOW() - INTERVAL '60 minutes';
```

### Dispatcher lag (seconds)

```sql
SELECT
    EXTRACT(EPOCH FROM (NOW() - MIN(next_run_at)))::int AS lag_seconds
FROM scheduled_actions
WHERE status = 'active'
  AND next_run_at <= NOW();
```

### Send failures count (15m)

```sql
SELECT COUNT(*) AS send_failed_count
FROM scheduled_action_runs
WHERE started_at >= NOW() - INTERVAL '15 minutes'
  AND error_code = 'send_failed';
```
