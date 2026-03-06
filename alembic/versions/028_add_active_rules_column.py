"""Add active_rules JSONB column to user_profiles.

Revision ID: 028
Revises: 027
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "028"
down_revision = "027"


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("active_rules", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "active_rules")
