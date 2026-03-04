"""Dashboard SQL query templates for SIA operational metrics.

Five PRD metrics:
  1. Activation Rate — % of active families using SIA
  2. Reliability — success/partial rate over last 7 days
  3. Source Freshness — avg time between data collection and message send
  4. Engagement — % of messages that receive a callback interaction
  5. Cost — avg tokens and model cost per run
"""

# ---------------------------------------------------------------------------
# M1: Activation Rate
# ---------------------------------------------------------------------------
# Percentage of onboarded families with at least one active scheduled action.
# Returns: active_families, total_families, activation_pct

ACTIVATION_RATE_SQL = """\
SELECT
    COUNT(DISTINCT sa.family_id) AS active_families,
    (SELECT COUNT(DISTINCT family_id) FROM users WHERE onboarded = TRUE) AS total_families,
    ROUND(
        COUNT(DISTINCT sa.family_id)::numeric * 100
        / NULLIF((SELECT COUNT(DISTINCT family_id) FROM users WHERE onboarded = TRUE), 0),
        2
    ) AS activation_pct
FROM scheduled_actions sa
WHERE sa.status = 'active';
"""

# ---------------------------------------------------------------------------
# M2: Reliability — success rate over last 7 days
# ---------------------------------------------------------------------------
# Returns: total_runs, succeeded, partial, failed, skipped, success_rate_pct

RELIABILITY_SQL = """\
SELECT
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (WHERE status = 'success') AS succeeded,
    COUNT(*) FILTER (WHERE status = 'partial') AS partial,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    COUNT(*) FILTER (WHERE status = 'skipped') AS skipped,
    ROUND(
        COUNT(*) FILTER (WHERE status IN ('success', 'partial'))::numeric * 100
        / NULLIF(COUNT(*), 0),
        2
    ) AS success_rate_pct
FROM scheduled_action_runs
WHERE started_at >= NOW() - INTERVAL '7 days';
"""

# ---------------------------------------------------------------------------
# M3: Source Freshness — avg duration_ms per run (last 7 days)
# ---------------------------------------------------------------------------
# Returns: avg_duration_ms, p50_duration_ms, p95_duration_ms

SOURCE_FRESHNESS_SQL = """\
SELECT
    ROUND(AVG(duration_ms)) AS avg_duration_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_duration_ms
FROM scheduled_action_runs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND status IN ('success', 'partial')
  AND duration_ms IS NOT NULL;
"""

# ---------------------------------------------------------------------------
# M4: Engagement — callback interaction rate (last 7 days)
# ---------------------------------------------------------------------------
# Approximated via scheduled_action_runs that have a non-null message_preview
# vs callback entries in the same period. Requires joining with callback logs
# if available; otherwise counts runs with user activity within 10 min.
# Simplified version: ratio of runs followed by a user message within 10 min.

ENGAGEMENT_SQL = """\
SELECT
    COUNT(*) AS total_delivered,
    COUNT(*) FILTER (
        WHERE EXISTS (
            SELECT 1 FROM scheduled_action_runs r2
            WHERE r2.scheduled_action_id = r.scheduled_action_id
              AND r2.id != r.id
              AND r2.started_at BETWEEN r.finished_at AND r.finished_at + INTERVAL '10 minutes'
        )
    ) AS with_followup,
    ROUND(
        COUNT(*) FILTER (
            WHERE EXISTS (
                SELECT 1 FROM scheduled_action_runs r2
                WHERE r2.scheduled_action_id = r.scheduled_action_id
                  AND r2.id != r.id
                  AND r2.started_at BETWEEN r.finished_at
                      AND r.finished_at + INTERVAL '10 minutes'
            )
        )::numeric * 100 / NULLIF(COUNT(*), 0),
        2
    ) AS engagement_pct
FROM scheduled_action_runs r
WHERE r.started_at >= NOW() - INTERVAL '7 days'
  AND r.status IN ('success', 'partial');
"""

# ---------------------------------------------------------------------------
# M5: Cost — avg tokens and model distribution (last 7 days)
# ---------------------------------------------------------------------------
# Returns: avg_tokens, total_tokens, model_distribution (per-model counts)

COST_SQL = """\
SELECT
    ROUND(AVG(tokens_used)) AS avg_tokens,
    SUM(tokens_used) AS total_tokens,
    model_used,
    COUNT(*) AS runs_count
FROM scheduled_action_runs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND tokens_used IS NOT NULL
GROUP BY model_used
ORDER BY runs_count DESC;
"""

# ---------------------------------------------------------------------------
# All metrics in one dict for easy iteration
# ---------------------------------------------------------------------------

DASHBOARD_QUERIES = {
    "activation_rate": ACTIVATION_RATE_SQL,
    "reliability": RELIABILITY_SQL,
    "source_freshness": SOURCE_FRESHNESS_SQL,
    "engagement": ENGAGEMENT_SQL,
    "cost": COST_SQL,
}
