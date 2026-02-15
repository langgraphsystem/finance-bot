"""Add life_events table and user_context.preferences column.

Revision ID: 004
Revises: 003
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    op.create_table(
        "life_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "note", "food", "drink", "mood", "task", "reflection",
                name="life_event_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("text", sa.Text, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("data", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── 3. Indexes ──────────────────────────────────────────────
    op.create_index("ix_life_events_family_date", "life_events", ["family_id", "date"])
    op.create_index("ix_life_events_user_date", "life_events", ["user_id", "date"])
    op.create_index(
        "ix_life_events_family_type_date", "life_events", ["family_id", "type", "date"]
    )
    op.execute("CREATE INDEX ix_life_events_tags ON life_events USING GIN (tags)")

    # ── 4. Enable RLS on life_events ────────────────────────────
    op.execute("ALTER TABLE life_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY life_events_family_isolation ON life_events "
        "USING (family_id = current_setting('app.current_family_id')::uuid)"
    )

    # ── 5. Add preferences column to user_context ───────────────
    op.add_column(
        "user_context",
        sa.Column("preferences", JSONB, server_default="{}", nullable=True),
    )


def downgrade() -> None:
    # ── Drop preferences column ─────────────────────────────────
    op.drop_column("user_context", "preferences")

    # ── Drop RLS policy ─────────────────────────────────────────
    op.execute("DROP POLICY IF EXISTS life_events_family_isolation ON life_events")

    # ── Drop life_events table ──────────────────────────────────
    op.drop_table("life_events")

    # ── Drop enum ───────────────────────────────────────────────
    op.execute("DROP TYPE IF EXISTS life_event_type")
