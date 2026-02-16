"""Add life_events table and user_context.preferences column.

Revision ID: 004
Revises: 003
Create Date: 2026-02-15
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create life_event_type enum ──────────────────────────
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "CREATE TYPE life_event_type AS ENUM "
            "('note', 'food', 'drink', 'mood', 'task', 'reflection'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )
    )

    # ── 2. Create life_events table ─────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS life_events ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  type life_event_type NOT NULL,"
            "  date DATE NOT NULL,"
            "  text TEXT,"
            "  tags JSONB,"
            "  data JSONB,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 3. Indexes ──────────────────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_life_events_family_date ON life_events (family_id, date)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_life_events_user_date ON life_events (user_id, date)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_life_events_family_type_date "
        "ON life_events (family_id, type, date)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_life_events_tags ON life_events USING GIN (tags)")

    # ── 4. Enable RLS on life_events ────────────────────────────
    op.execute("ALTER TABLE life_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "CREATE POLICY life_events_family_isolation ON life_events "
        "USING (family_id = current_setting('app.current_family_id')::uuid); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    # ── 5. Add preferences column to user_context ───────────────
    op.execute("ALTER TABLE user_context ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'")


def downgrade() -> None:
    # ── Drop preferences column ─────────────────────────────────
    op.drop_column("user_context", "preferences")

    # ── Drop RLS policy ─────────────────────────────────────────
    op.execute("DROP POLICY IF EXISTS life_events_family_isolation ON life_events")

    # ── Drop life_events table ──────────────────────────────────
    op.drop_table("life_events")

    # ── Drop enum ───────────────────────────────────────────────
    op.execute("DROP TYPE IF EXISTS life_event_type")
