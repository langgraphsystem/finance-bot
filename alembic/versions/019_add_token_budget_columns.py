"""Add cache token columns to usage_logs for token budget monitoring.

Revision ID: 019
Revises: 018
"""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE usage_logs
        ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS cache_creation_tokens INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS overflow_layers_dropped TEXT DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE usage_logs
        DROP COLUMN IF EXISTS cache_read_tokens,
        DROP COLUMN IF EXISTS cache_creation_tokens,
        DROP COLUMN IF EXISTS overflow_layers_dropped
    """)
