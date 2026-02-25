"""Add locale v2 fields to user_profiles.

Revision ID: 013
Revises: 012
Create Date: 2026-02-25
"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles "
        "ADD COLUMN IF NOT EXISTS notification_language VARCHAR(10)"
    )
    op.execute(
        "ALTER TABLE user_profiles "
        "ADD COLUMN IF NOT EXISTS timezone_source VARCHAR(32) DEFAULT 'default'"
    )
    op.execute(
        "ALTER TABLE user_profiles "
        "ADD COLUMN IF NOT EXISTS timezone_confidence INTEGER DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE user_profiles "
        "ADD COLUMN IF NOT EXISTS locale_updated_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS locale_updated_at")
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS timezone_confidence")
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS timezone_source")
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS notification_language")

