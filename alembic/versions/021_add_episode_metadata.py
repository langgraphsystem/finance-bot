"""Add metadata JSONB column to session_summaries for episodic memory.

Stores episode metadata: topics, intents_used, outcome, satisfaction signals.
Enables "do the same as last time" by searching past episodes.

Revision ID: 021
Revises: 020
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE session_summaries
        ADD COLUMN IF NOT EXISTS episode_metadata JSONB DEFAULT '{}'::jsonb
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE session_summaries
        DROP COLUMN IF EXISTS episode_metadata
    """)
