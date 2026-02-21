"""Add deadline_notified_at to tasks table.

Prevents duplicate proactive deadline notifications by tracking
when a user was last notified about an upcoming task deadline.

Revision ID: 008
Revises: 007
Create Date: 2026-02-21
"""

import sqlalchemy as sa

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("deadline_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "deadline_notified_at")
