"""Add sheet_sync_configs table for Google Sheets sync.

Revision ID: 014
Revises: 013
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sheet_sync_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            spreadsheet_id VARCHAR(128) NOT NULL,
            sheet_name VARCHAR(64) DEFAULT 'Expenses',
            sync_scope VARCHAR(32) DEFAULT 'expenses',
            shared_emails TEXT[],
            last_synced_at TIMESTAMPTZ,
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sheet_sync_family "
        "ON sheet_sync_configs (family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sheet_sync_active "
        "ON sheet_sync_configs (is_active) WHERE is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sheet_sync_configs")
