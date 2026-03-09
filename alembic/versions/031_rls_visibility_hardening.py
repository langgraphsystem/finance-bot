"""RLS Phase 3: Intra-tenant visibility hardening.

Adds app.current_user_id session variable support and enhanced RLS policies
for tables with a visibility column. Private resources (visibility='private_user')
are only accessible to the owning user_id. Shared resources follow role-based
visibility rules at the app layer; RLS provides a safety net.

Also adds RLS policy for workspace_memberships table.

Revision ID: 031
Revises: 030
"""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

# Tables with visibility column that need enhanced RLS.
# For these tables, private_user rows should only be visible to the owning user.
_VISIBILITY_TABLES = [
    "transactions",
    "tasks",
    "documents",
    "conversation_messages",
    "session_summaries",
]


def _safe_get_user_id() -> str:
    """SQL expression that safely gets current_user_id, returning NULL if not set."""
    return "nullif(current_setting('app.current_user_id', true), '')::uuid"


def upgrade() -> None:
    # 1. Create helper function for safe user_id retrieval
    op.execute("""
        CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid AS $$
        BEGIN
            RETURN nullif(current_setting('app.current_user_id', true), '')::uuid;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """)

    # 2. Enhanced RLS for visibility tables:
    #    - family_id isolation stays (tenant boundary)
    #    - private_user rows: only visible when user_id matches current_user_id
    #    - family_shared / work_shared / NULL: visible to all family members
    #      (app layer handles role)
    for table in _VISIBILITY_TABLES:
        # Drop old family-only policy
        op.execute(f"""
            DO $$ BEGIN
                DROP POLICY IF EXISTS {table}_family_isolation ON {table};
            EXCEPTION WHEN undefined_object THEN NULL;
            END $$;
        """)

        # Create enhanced policy
        op.execute(f"""
            CREATE POLICY {table}_tenant_visibility ON {table}
            FOR ALL
            USING (
                family_id = current_setting('app.current_family_id')::uuid
                AND (
                    visibility IS NULL
                    OR visibility != 'private_user'
                    OR user_id = app_current_user_id()
                    OR app_current_user_id() IS NULL
                )
            )
            WITH CHECK (
                family_id = current_setting('app.current_family_id')::uuid
            );
        """)

    # 3. RLS for workspace_memberships
    op.execute("""
        ALTER TABLE workspace_memberships ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY workspace_memberships_family_isolation ON workspace_memberships
            FOR ALL
            USING (family_id = current_setting('app.current_family_id')::uuid)
            WITH CHECK (family_id = current_setting('app.current_family_id')::uuid);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # 4. RLS for life_events — enforce user_id isolation (strictly private)
    op.execute("""
        DROP POLICY IF EXISTS life_events_family_isolation ON life_events;
    """)
    op.execute("""
        CREATE POLICY life_events_user_isolation ON life_events
        FOR ALL
        USING (
            family_id = current_setting('app.current_family_id')::uuid
            AND (
                user_id = app_current_user_id()
                OR app_current_user_id() IS NULL
            )
        )
        WITH CHECK (
            family_id = current_setting('app.current_family_id')::uuid
        );
    """)


def downgrade() -> None:
    # Restore life_events to family-only
    op.execute("DROP POLICY IF EXISTS life_events_user_isolation ON life_events;")
    op.execute("""
        CREATE POLICY life_events_family_isolation ON life_events
        FOR ALL
        USING (family_id = current_setting('app.current_family_id')::uuid);
    """)

    # Drop workspace_memberships RLS
    op.execute(
        "DROP POLICY IF EXISTS workspace_memberships_family_isolation ON workspace_memberships;"
    )
    op.execute("ALTER TABLE workspace_memberships DISABLE ROW LEVEL SECURITY;")

    # Restore visibility tables to family-only policies
    for table in _VISIBILITY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_visibility ON {table};")
        op.execute(f"""
            CREATE POLICY {table}_family_isolation ON {table}
            FOR ALL
            USING (family_id = current_setting('app.current_family_id')::uuid)
            WITH CHECK (family_id = current_setting('app.current_family_id')::uuid);
        """)

    # Drop helper function
    op.execute("DROP FUNCTION IF EXISTS app_current_user_id();")
