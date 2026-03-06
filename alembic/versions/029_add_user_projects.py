"""Add user_projects table and active_project_id to user_context (Phase 12).

Revision ID: 029
Revises: 028
"""

import sqlalchemy as sa

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create project_status enum
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE project_status AS ENUM ('active', 'paused', 'completed', 'archived'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # Create user_projects table
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            user_id UUID NOT NULL REFERENCES users(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            status project_status NOT NULL DEFAULT 'active',
            metadata_extra JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_projects_user_status "
        "ON user_projects (user_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_projects_family "
        "ON user_projects (family_id)"
    )

    # Add active_project_id to user_context
    op.add_column(
        "user_context",
        sa.Column("active_project_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "ALTER TABLE user_context "
        "ADD CONSTRAINT fk_user_context_active_project "
        "FOREIGN KEY (active_project_id) REFERENCES user_projects(id) "
        "ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_context DROP CONSTRAINT IF EXISTS fk_user_context_active_project"
    )
    op.drop_column("user_context", "active_project_id")
    op.execute("DROP TABLE IF EXISTS user_projects")
    op.execute("DROP TYPE IF EXISTS project_status")
