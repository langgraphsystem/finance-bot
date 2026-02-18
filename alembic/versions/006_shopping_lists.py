"""Add shopping_lists and shopping_list_items tables.

Revision ID: 006
Revises: 005
Create Date: 2026-02-18
"""

import sqlalchemy as sa

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create shopping_lists table ─────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS shopping_lists ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  name VARCHAR(100) NOT NULL DEFAULT 'grocery',"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_at TIMESTAMPTZ DEFAULT now()"
            ")"
        )
    )

    # ── 2. Create shopping_list_items table ────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS shopping_list_items ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  list_id UUID NOT NULL REFERENCES shopping_lists(id) ON DELETE CASCADE,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  name VARCHAR(300) NOT NULL,"
            "  quantity VARCHAR(50),"
            "  is_checked BOOLEAN DEFAULT false,"
            "  checked_at TIMESTAMPTZ,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 3. Indexes ─────────────────────────────────────────────────
    indexes = [
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_shopping_list_family_name "
            "ON shopping_lists(family_id, lower(name))"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_shopping_list_items_list "
            "ON shopping_list_items(list_id, is_checked)"
        ),
        ("CREATE INDEX IF NOT EXISTS idx_shopping_lists_family ON shopping_lists(family_id)"),
    ]
    for idx in indexes:
        op.execute(sa.text(idx))

    # ── 4. Enable RLS ──────────────────────────────────────────────
    for table in ["shopping_lists", "shopping_list_items"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"DO $$ BEGIN "
            f"CREATE POLICY {table}_family_isolation ON {table} "
            f"USING (family_id = current_setting('app.current_family_id')::uuid); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )


def downgrade() -> None:
    for table in ["shopping_list_items", "shopping_lists"]:
        op.execute(f"DROP POLICY IF EXISTS {table}_family_isolation ON {table}")
    op.execute("DROP TABLE IF EXISTS shopping_list_items CASCADE")
    op.execute("DROP TABLE IF EXISTS shopping_lists CASCADE")
