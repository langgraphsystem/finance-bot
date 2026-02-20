"""Add city column to user_profiles for location-aware maps search.

Revision ID: 008
Revises: 007
Create Date: 2026-02-19
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS city VARCHAR(255)")


def downgrade() -> None:
    op.drop_column("user_profiles", "city")
