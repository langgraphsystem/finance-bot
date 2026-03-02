"""Add orchestrator dead-letter queue table.

Revision ID: 025
Revises: 024
Create Date: 2026-03-02
"""

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS orchestrator_dlq (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            graph_name VARCHAR(64) NOT NULL,
            thread_id VARCHAR(256) NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id),
            family_id UUID NOT NULL REFERENCES families(id),
            error TEXT NOT NULL,
            state JSONB,
            retried BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            retried_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dlq_user_id
        ON orchestrator_dlq (user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dlq_graph_created
        ON orchestrator_dlq (graph_name, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS orchestrator_dlq")
