"""Add invoice tax fields and sales-tax cache table.

Revision ID: 024
Revises: 023
"""

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS subtotal NUMERIC(12,2),
        ADD COLUMN IF NOT EXISTS tax_amount NUMERIC(12,2) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(8,6) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS tax_source VARCHAR(32),
        ADD COLUMN IF NOT EXISTS tax_jurisdiction VARCHAR(128)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sales_tax_rate_cache (
            id UUID PRIMARY KEY,
            seller_state VARCHAR(16) NOT NULL,
            buyer_state VARCHAR(16) NOT NULL,
            buyer_postal_code VARCHAR(20) NOT NULL,
            tax_category VARCHAR(64) NOT NULL DEFAULT 'general',
            currency VARCHAR(10) NOT NULL DEFAULT 'USD',
            tax_rate NUMERIC(8,6) NOT NULL DEFAULT 0,
            source VARCHAR(32) NOT NULL DEFAULT 'stripe',
            jurisdiction VARCHAR(128),
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sales_tax_rate_cache_lookup "
        "ON sales_tax_rate_cache (seller_state, buyer_state, buyer_postal_code, tax_category, "
        "currency, expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sales_tax_rate_cache_lookup")
    op.execute("DROP TABLE IF EXISTS sales_tax_rate_cache")
    op.execute("""
        ALTER TABLE invoices
        DROP COLUMN IF EXISTS tax_jurisdiction,
        DROP COLUMN IF EXISTS tax_source,
        DROP COLUMN IF EXISTS tax_rate,
        DROP COLUMN IF EXISTS tax_amount,
        DROP COLUMN IF EXISTS subtotal
    """)
