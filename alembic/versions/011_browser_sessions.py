"""Add browser session and action log tables.

Revision ID: 011
Revises: 010
"""

import sqlalchemy as sa

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS user_browser_sessions ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  site VARCHAR(255) NOT NULL,"
            "  storage_state_encrypted BYTEA NOT NULL,"
            "  meta JSONB,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  expires_at TIMESTAMPTZ"
            ")"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uix_browser_sessions_user_site ON user_browser_sessions(user_id, site)"
        )
    )
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS browser_action_logs ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  session_id UUID REFERENCES user_browser_sessions(id),"
            "  action_type VARCHAR(50) NOT NULL,"
            "  url VARCHAR(2048),"
            "  details JSONB,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE user_browser_sessions ENABLE ROW LEVEL SECURITY"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "CREATE POLICY browser_sessions_family_isolation "
            "ON user_browser_sessions "
            "USING (family_id::text = current_setting('app.current_family_id', true)); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS browser_action_logs"))
    op.execute(sa.text("DROP TABLE IF EXISTS user_browser_sessions"))
