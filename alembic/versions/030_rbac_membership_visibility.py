"""Add workspace_memberships table, visibility columns, and RBAC enums.

Revision ID: 030
Revises: 029
"""
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_type AS ENUM ('family', 'worker');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_role AS ENUM (
                'owner', 'partner', 'family_member', 'worker',
                'assistant', 'accountant', 'viewer', 'custom'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE membership_status AS ENUM ('invited', 'active', 'suspended', 'revoked');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # --- workspace_memberships table ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_memberships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            user_id UUID NOT NULL REFERENCES users(id),
            membership_type membership_type NOT NULL,
            role membership_role NOT NULL,
            permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
            status membership_status NOT NULL DEFAULT 'active',
            invited_by_user_id UUID REFERENCES users(id),
            joined_at TIMESTAMPTZ DEFAULT now(),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(family_id, user_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wm_family_user "
        "ON workspace_memberships (family_id, user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wm_user_status "
        "ON workspace_memberships (user_id, status)"
    )

    # --- visibility columns ---
    op.execute(
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS visibility VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS visibility VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE conversation_messages "
        "ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )
    op.execute(
        "ALTER TABLE session_summaries "
        "ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'private_user'"
    )

    # --- Backfill transactions visibility from scope ---
    op.execute("""
        UPDATE transactions SET visibility = CASE
            WHEN scope = 'personal' THEN 'private_user'
            WHEN scope = 'family' THEN 'family_shared'
            WHEN scope = 'business' THEN 'work_shared'
        END
        WHERE visibility IS NULL
    """)

    # --- Backfill documents visibility ---
    op.execute("""
        UPDATE documents SET visibility = CASE
            WHEN type IN ('template', 'invoice', 'report', 'spreadsheet') THEN 'work_shared'
            ELSE 'private_user'
        END
        WHERE visibility IS NULL
    """)

    # --- Backfill existing users into workspace_memberships ---
    op.execute("""
        INSERT INTO workspace_memberships (
            id,
            family_id,
            user_id,
            membership_type,
            role,
            permissions,
            status,
            joined_at
        )
        SELECT
            gen_random_uuid(),
            u.family_id,
            u.id,
            'family'::membership_type,
            CASE
                WHEN u.role = 'owner' THEN 'owner'::membership_role
                ELSE 'family_member'::membership_role
            END,
            CASE
                WHEN u.role = 'owner' THEN
                    '[
                        "view_finance","create_finance","edit_finance","delete_finance",
                        "view_reports","export_reports","view_budgets","manage_budgets",
                        "view_work_tasks","manage_work_tasks","view_work_documents",
                        "manage_work_documents","view_contacts","manage_contacts",
                        "invite_members","manage_members"
                    ]'::jsonb
                ELSE '["create_finance","view_budgets"]'::jsonb
            END,
            'active'::membership_status,
            u.created_at
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1
            FROM workspace_memberships wm
            WHERE wm.user_id = u.id
              AND wm.family_id = u.family_id
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE session_summaries DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS visibility")
    op.execute("DROP TABLE IF EXISTS workspace_memberships")
    op.execute("DROP TYPE IF EXISTS membership_status")
    op.execute("DROP TYPE IF EXISTS membership_role")
    op.execute("DROP TYPE IF EXISTS membership_type")
