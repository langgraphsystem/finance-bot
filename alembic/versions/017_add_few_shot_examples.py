"""Add few_shot_examples table with pgvector.

Revision ID: 017
Revises: 016
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE IF NOT EXISTS few_shot_examples (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id UUID NOT NULL REFERENCES families(id),
            user_message TEXT NOT NULL,
            detected_intent VARCHAR NOT NULL,
            corrected_intent VARCHAR,
            intent_data JSONB,
            embedding vector(1536),
            usage_count INTEGER DEFAULT 0,
            accuracy_score FLOAT DEFAULT 1.0,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_few_shot_family"
        " ON few_shot_examples (family_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_few_shot_intent"
        " ON few_shot_examples (detected_intent)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS few_shot_examples")
