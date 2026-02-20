"""Add recurrence columns to tasks for recurring reminders.

Revision ID: 009
Revises: 008
Create Date: 2026-02-19
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE IF NOT EXISTS reminder_recurrence "
        "AS ENUM ('none', 'daily', 'weekly', 'monthly')"
    )
    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS recurrence reminder_recurrence NOT NULL DEFAULT 'none', "
        "ADD COLUMN IF NOT EXISTS recurrence_end_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS original_reminder_time VARCHAR(10)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS original_reminder_time")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS recurrence_end_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS recurrence")
    op.execute("DROP TYPE IF EXISTS reminder_recurrence")
