"""Add document versioning columns.

Revision ID: 015
Revises: 014
Create Date: 2026-02-28
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Document versioning
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS parent_document_id UUID "
        "REFERENCES documents(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_parent_document_id "
        "ON documents (parent_document_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_parent_document_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS parent_document_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS version")
