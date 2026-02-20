"""Backfill user_profiles for existing users who lack one.

Revision ID: 010
Revises: 009
Create Date: 2026-02-20
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO user_profiles (id, family_id, user_id, display_name, timezone,
                                   preferred_language, created_at, updated_at)
        SELECT gen_random_uuid(), u.family_id, u.id, u.name, 'America/New_York',
               u.language, NOW(), NOW()
        FROM users u
        LEFT JOIN user_profiles up ON up.user_id = u.id
        WHERE up.id IS NULL
    """)


def downgrade() -> None:
    pass
