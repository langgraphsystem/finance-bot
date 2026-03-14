"""add_trackers_and_tracker_entries

Revision ID: f9720751be03
Revises: 033
Create Date: 2026-03-14 10:50:48.727877

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "f9720751be03"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trackers (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id   UUID NOT NULL REFERENCES families(id),
            user_id     UUID NOT NULL REFERENCES users(id),
            tracker_type VARCHAR(32) NOT NULL,
            name         VARCHAR(128) NOT NULL,
            emoji        VARCHAR(8),
            description  TEXT,
            config       JSONB,
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tracker_entries (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tracker_id  UUID NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
            family_id   UUID NOT NULL REFERENCES families(id),
            user_id     UUID NOT NULL REFERENCES users(id),
            date        DATE NOT NULL,
            value       INTEGER,
            data        JSONB,
            note        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Indexes for fast queries
    op.execute("CREATE INDEX IF NOT EXISTS ix_trackers_family_user ON trackers(family_id, user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracker_entries_tracker_date ON tracker_entries(tracker_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tracker_entries_family_date ON tracker_entries(family_id, date)")

    # RLS policies (same pattern as other tables)
    op.execute("ALTER TABLE trackers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tracker_entries ENABLE ROW LEVEL SECURITY")

    op.execute("""
        DO $$ BEGIN
            CREATE POLICY trackers_family_isolation ON trackers
                USING (family_id::text = current_setting('app.current_family_id', true));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE POLICY tracker_entries_family_isolation ON tracker_entries
                USING (family_id::text = current_setting('app.current_family_id', true));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tracker_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS trackers CASCADE")
