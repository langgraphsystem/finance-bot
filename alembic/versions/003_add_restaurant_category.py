"""Add 'Рестораны/Кафе' category to all existing families.

Revision ID: 003
Revises: 002
Create Date: 2026-02-14
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO categories (id, family_id, name, scope, icon, is_default)
        SELECT
            gen_random_uuid(),
            f.id,
            'Рестораны/Кафе',
            'family',
            '🍽️',
            true
        FROM families f
        WHERE NOT EXISTS (
            SELECT 1 FROM categories c
            WHERE c.family_id = f.id AND c.name = 'Рестораны/Кафе'
        );
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM categories
        WHERE name = 'Рестораны/Кафе' AND is_default = true;
    """)
