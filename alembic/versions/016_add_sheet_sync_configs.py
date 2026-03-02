"""Add sheet_sync_configs table.

Revision ID: 016
Revises: 015
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sheet_sync_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            spreadsheet_id VARCHAR NOT NULL,
            sheet_name VARCHAR DEFAULT 'Expenses',
            sync_scope VARCHAR DEFAULT 'expenses',
            is_active BOOLEAN DEFAULT true,
            last_synced_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sheet_sync_configs_family"
        " ON sheet_sync_configs (family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sheet_sync_configs_active"
        " ON sheet_sync_configs (is_active) WHERE is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sheet_sync_configs")
