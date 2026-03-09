"""Drop duplicate index on workspace_memberships.

The UNIQUE constraint on (family_id, user_id) already creates an index.
The explicit ix_wm_family_user index is redundant.

Revision ID: 032
Revises: 031
"""

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_wm_family_user;")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wm_family_user "
        "ON workspace_memberships (family_id, user_id);"
    )
