"""Fix Samat's Walmart category and add Shell merchant mapping.

Revision ID: 027
Revises: 026
"""

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None

SAMAT_FAMILY_ID = "7cf7c7b6-339f-4b54-a4e1-d20cbcfee7e3"
DIESEL_CATEGORY_ID = "9cfad328-5a1c-45a4-bbc3-42f828255228"
PRODUKTY_CATEGORY_ID = "8acd4519-841a-486a-8fd5-9ff0eddd4325"
WALMART_TX_ID = "836ba5b3-0829-487f-b548-66579321b49b"


def upgrade() -> None:
    # Fix Walmart Supercenter: move from Дизель → Продукты
    op.execute(
        f"""
        UPDATE transactions
        SET category_id = '{PRODUKTY_CATEGORY_ID}'
        WHERE id = '{WALMART_TX_ID}'
          AND family_id = '{SAMAT_FAMILY_ID}'
          AND category_id = '{DIESEL_CATEGORY_ID}'
        """
    )

    # Add missing 'shell' merchant mapping (idempotent)
    op.execute(
        f"""
        INSERT INTO merchant_mappings
            (id, family_id, merchant_pattern, category_id, scope, confidence)
        SELECT gen_random_uuid(), '{SAMAT_FAMILY_ID}', 'shell',
               '{DIESEL_CATEGORY_ID}', 'business', 0.9
        WHERE NOT EXISTS (
            SELECT 1 FROM merchant_mappings
            WHERE family_id = '{SAMAT_FAMILY_ID}'
              AND merchant_pattern = 'shell'
        )
        """
    )


def downgrade() -> None:
    # Revert Walmart back to Дизель
    op.execute(
        f"""
        UPDATE transactions
        SET category_id = '{DIESEL_CATEGORY_ID}'
        WHERE id = '{WALMART_TX_ID}'
          AND family_id = '{SAMAT_FAMILY_ID}'
        """
    )

    # Remove shell mapping
    op.execute(
        f"""
        DELETE FROM merchant_mappings
        WHERE family_id = '{SAMAT_FAMILY_ID}'
          AND merchant_pattern = 'shell'
        """
    )
