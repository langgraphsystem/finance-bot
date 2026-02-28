"""Add document agent fields and new document types.

Revision ID: 014
Revises: 5be502c5e65f
Create Date: 2026-02-28
"""

from alembic import op

revision = "014"
down_revision = "5be502c5e65f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new values to document_type enum
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'contract'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'form'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'report'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'template'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'spreadsheet'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'presentation'")

    # Add new columns to documents table
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS title VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS extracted_text TEXT"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata_extra JSONB"
    )

    # Add indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_family_id ON documents (family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_type ON documents (type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)"
    )

    # Enable pg_trgm for fast ILIKE search on extracted_text and title
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_extracted_text_trgm "
        "ON documents USING gin (extracted_text gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_title_trgm "
        "ON documents USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_documents_extracted_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_documents_content_hash")
    op.execute("DROP INDEX IF EXISTS ix_documents_type")
    op.execute("DROP INDEX IF EXISTS ix_documents_family_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS metadata_extra")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content_hash")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS extracted_text")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS page_count")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS file_size_bytes")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS mime_type")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS file_name")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS title")
