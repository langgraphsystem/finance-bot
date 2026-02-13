"""RLS policies, pgvector extension, and category embeddings.

Revision ID: 002
Revises: 001
Create Date: 2026-02-13
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# All 12 tables that have a family_id column
RLS_TABLES = [
    "users",
    "categories",
    "documents",
    "transactions",
    "merchant_mappings",
    "loads",
    "conversation_messages",
    "user_context",
    "session_summaries",
    "audit_log",
    "recurring_payments",
    "budgets",
]


def upgrade() -> None:
    # ── 1. Enable RLS on all family-scoped tables ────────────────
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # ── 2. Helper function to set family context ─────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_family_context(family_uuid uuid) RETURNS void AS $$
        BEGIN
          PERFORM set_config('app.current_family_id', family_uuid::text, true);
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── 3. Create RLS policies for each table ────────────────────
    for table in RLS_TABLES:
        policy = f"{table}_family_isolation"
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
              FOR ALL
              USING (family_id = current_setting('app.current_family_id', true)::uuid)
              WITH CHECK (family_id = current_setting('app.current_family_id', true)::uuid)
            """
        )

    # ── 4. Enable pgvector extension ─────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 5. Add embedding column to categories ────────────────────
    op.execute("ALTER TABLE categories ADD COLUMN embedding vector(1536)")


def downgrade() -> None:
    # ── Drop embedding column ────────────────────────────────────
    op.execute("ALTER TABLE categories DROP COLUMN IF EXISTS embedding")

    # ── Drop all RLS policies ────────────────────────────────────
    for table in RLS_TABLES:
        policy = f"{table}_family_isolation"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    # ── Disable RLS on all tables ────────────────────────────────
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Drop the helper function ─────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS set_family_context(uuid)")

    # ── Drop pgvector extension ──────────────────────────────────
    op.execute("DROP EXTENSION IF EXISTS vector")
