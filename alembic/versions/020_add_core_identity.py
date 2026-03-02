"""Add core_identity JSONB column to user_profiles.

Core identity stores permanent user facts (name, occupation, family,
preferred currency, business type, communication preferences) that
are never dropped during overflow trimming.

Revision ID: 020
Revises: 019
"""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
        ADD COLUMN IF NOT EXISTS core_identity JSONB DEFAULT '{}'::jsonb
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE user_profiles
        DROP COLUMN IF EXISTS core_identity
    """)
