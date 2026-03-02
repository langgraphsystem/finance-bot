"""Add memory_graph table for relationship tracking.

PostgreSQL fallback for graph memory — tracks entity relationships
(person→company, person→person, merchant→category, etc.)

Revision ID: 022
Revises: 021
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_graph (
            id SERIAL PRIMARY KEY,
            family_id UUID NOT NULL REFERENCES families(id),
            subject_type VARCHAR(50) NOT NULL,
            subject_id VARCHAR(255) NOT NULL,
            relation VARCHAR(100) NOT NULL,
            object_type VARCHAR(50) NOT NULL,
            object_id VARCHAR(255) NOT NULL,
            strength FLOAT DEFAULT 1.0,
            graph_metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_memory_graph_subject
        ON memory_graph (family_id, subject_type, subject_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_memory_graph_object
        ON memory_graph (family_id, object_type, object_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_memory_graph_relation
        ON memory_graph (family_id, relation)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory_graph")
