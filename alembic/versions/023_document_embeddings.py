"""Add document_embeddings table for semantic search.

Stores chunked document text with vector embeddings (text-embedding-3-small,
dimension 1536) for hybrid search (pg_trgm + pgvector RRF).

Revision ID: 023
Revises: 022
"""

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            id SERIAL PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            family_id UUID NOT NULL REFERENCES families(id),
            chunk_index INTEGER NOT NULL DEFAULT 0,
            chunk_text TEXT NOT NULL,
            embedding vector(1536),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # HNSW index for fast approximate nearest-neighbor search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_doc_emb_vector
        ON document_embeddings USING hnsw (embedding vector_cosine_ops)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_doc_emb_document_id
        ON document_embeddings (document_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_doc_emb_family_id
        ON document_embeddings (family_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_embeddings")
