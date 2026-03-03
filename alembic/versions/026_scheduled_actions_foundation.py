"""Add scheduled actions foundation tables.

Revision ID: 026
Revises: 025
Create Date: 2026-03-03
"""

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE schedule_kind AS ENUM ('once', 'daily', 'weekly', 'monthly', 'weekdays', "
        "'cron'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE action_status AS ENUM ('active', 'paused', 'completed', 'deleted'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE run_status AS ENUM ('pending', 'running', 'success', 'partial', 'failed', "
        "'skipped'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE output_mode AS ENUM ('compact', 'decision_ready'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            user_id UUID NOT NULL REFERENCES users(id),
            title VARCHAR(255) NOT NULL,
            instruction TEXT NOT NULL,
            action_kind VARCHAR(32) NOT NULL DEFAULT 'digest',
            schedule_kind schedule_kind NOT NULL,
            schedule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            output_mode output_mode NOT NULL DEFAULT 'compact',
            timezone VARCHAR(50) NOT NULL,
            language VARCHAR(10) NOT NULL DEFAULT 'en',
            status action_status NOT NULL DEFAULT 'active',
            next_run_at TIMESTAMPTZ,
            last_run_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            run_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            max_failures INTEGER NOT NULL DEFAULT 3,
            end_at TIMESTAMPTZ,
            max_runs INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_action_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scheduled_action_id UUID NOT NULL REFERENCES scheduled_actions(id) ON DELETE CASCADE,
            planned_run_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            status run_status NOT NULL DEFAULT 'pending',
            error_code VARCHAR(64),
            error_text TEXT,
            sources_status JSONB,
            payload_snapshot JSONB,
            message_preview TEXT,
            model_used VARCHAR(64),
            tokens_used INTEGER,
            duration_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_sched_run_idempotent UNIQUE (scheduled_action_id, planned_run_at)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sched_actions_dispatch
        ON scheduled_actions (status, next_run_at)
        WHERE status = 'active'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sched_actions_user
        ON scheduled_actions (family_id, user_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sched_runs_action_created
        ON scheduled_action_runs (scheduled_action_id, created_at DESC)
    """)

    op.execute("ALTER TABLE scheduled_actions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scheduled_action_runs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY scheduled_actions_family_isolation ON scheduled_actions
          FOR ALL
          USING (family_id = current_setting('app.current_family_id', true)::uuid)
          WITH CHECK (family_id = current_setting('app.current_family_id', true)::uuid)
    """)
    op.execute("""
        CREATE POLICY scheduled_action_runs_family_isolation ON scheduled_action_runs
          FOR ALL
          USING (
            EXISTS (
              SELECT 1
              FROM scheduled_actions sa
              WHERE sa.id = scheduled_action_runs.scheduled_action_id
                AND sa.family_id = current_setting('app.current_family_id', true)::uuid
            )
          )
          WITH CHECK (
            EXISTS (
              SELECT 1
              FROM scheduled_actions sa
              WHERE sa.id = scheduled_action_runs.scheduled_action_id
                AND sa.family_id = current_setting('app.current_family_id', true)::uuid
            )
          )
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS scheduled_action_runs_family_isolation ON scheduled_action_runs"
    )
    op.execute("DROP POLICY IF EXISTS scheduled_actions_family_isolation ON scheduled_actions")
    op.execute("ALTER TABLE scheduled_action_runs DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scheduled_actions DISABLE ROW LEVEL SECURITY")

    op.execute("DROP INDEX IF EXISTS ix_sched_runs_action_created")
    op.execute("DROP INDEX IF EXISTS ix_sched_actions_user")
    op.execute("DROP INDEX IF EXISTS ix_sched_actions_dispatch")

    op.execute("DROP TABLE IF EXISTS scheduled_action_runs")
    op.execute("DROP TABLE IF EXISTS scheduled_actions")

    op.execute("DROP TYPE IF EXISTS output_mode")
    op.execute("DROP TYPE IF EXISTS run_status")
    op.execute("DROP TYPE IF EXISTS action_status")
    op.execute("DROP TYPE IF EXISTS schedule_kind")
