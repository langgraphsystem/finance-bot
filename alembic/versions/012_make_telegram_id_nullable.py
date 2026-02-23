"""Make users.telegram_id nullable for non-Telegram channel registration.

Revision ID: 012
Revises: 011
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "telegram_id", nullable=True)
    # Replace simple unique constraint with partial unique index
    # (allows multiple NULLs while keeping uniqueness for non-null values)
    op.drop_index("ix_users_telegram_id", table_name="users", if_exists=True)
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id_unique "
        "ON users (telegram_id) WHERE telegram_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_id_unique")
    op.alter_column("users", "telegram_id", nullable=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
