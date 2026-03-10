"""fix_default_timezones_to_utc

Users with timezone_source='default' still have the old America/New_York
default. Migrate them to UTC so notifications don't fire at wrong times.

Revision ID: 033
Revises: 032
Create Date: 2026-03-10

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles "
        "ALTER COLUMN timezone SET DEFAULT 'UTC'"
    )
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'UTC' "
        "WHERE timezone_source = 'default' AND timezone = 'America/New_York'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles "
        "ALTER COLUMN timezone SET DEFAULT 'America/New_York'"
    )
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'America/New_York' "
        "WHERE timezone_source = 'default' "
        "AND timezone = 'UTC' "
        "AND created_at < TIMESTAMPTZ '2026-03-10 00:00:00+00'"
    )
