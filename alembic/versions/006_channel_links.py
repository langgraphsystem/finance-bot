"""Add channel_links table for multi-channel user mapping.

Revision ID: 006b
Revises: 005
Create Date: 2026-02-19
"""

import sqlalchemy as sa

from alembic import op

revision = "006b"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # channel_type enum already exists from migration 005

    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS channel_links ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  channel channel_type NOT NULL,"
            "  channel_user_id VARCHAR(255) NOT NULL,"
            "  channel_chat_id VARCHAR(255),"
            "  is_primary BOOLEAN DEFAULT false,"
            "  linked_at TIMESTAMPTZ DEFAULT now(),"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  CONSTRAINT uq_channel_user UNIQUE (channel, channel_user_id)"
            ")"
        )
    )

    # Indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_channel_links_family ON channel_links (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_channel_links_user ON channel_links (user_id)",
        (
            "CREATE INDEX IF NOT EXISTS ix_channel_links_lookup "
            "ON channel_links (channel, channel_user_id)"
        ),
    ]
    for idx in indexes:
        op.execute(idx)

    # RLS
    op.execute("ALTER TABLE channel_links ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "CREATE POLICY channel_links_family_isolation ON channel_links "
        "USING (family_id = current_setting('app.current_family_id')::uuid); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS channel_links_family_isolation ON channel_links")
    op.execute("DROP TABLE IF EXISTS channel_links CASCADE")
