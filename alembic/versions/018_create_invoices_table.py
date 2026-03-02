"""Create invoices table and add contact_id to transactions.

Revision ID: 018
Revises: 017
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE invoice_status AS ENUM ('draft', 'sent', 'paid', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id UUID PRIMARY KEY,
            family_id UUID NOT NULL REFERENCES families(id),
            user_id UUID NOT NULL REFERENCES users(id),
            contact_id UUID REFERENCES contacts(id),
            invoice_number VARCHAR(20) NOT NULL,
            status invoice_status NOT NULL DEFAULT 'draft',
            invoice_date DATE NOT NULL,
            due_date DATE NOT NULL,
            currency VARCHAR(10) NOT NULL DEFAULT 'USD',
            total NUMERIC(12,2) NOT NULL,
            items JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT,
            company_name VARCHAR(255),
            company_address TEXT,
            company_phone VARCHAR(50),
            client_name VARCHAR(255) NOT NULL,
            client_email VARCHAR(255),
            client_phone VARCHAR(50),
            document_id UUID REFERENCES documents(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoices_family_id
        ON invoices (family_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_invoices_contact_id
        ON invoices (contact_id)
    """)

    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS contact_id UUID REFERENCES contacts(id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_contact_id
        ON transactions (contact_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transactions_contact_id")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS contact_id")
    op.execute("DROP INDEX IF EXISTS ix_invoices_contact_id")
    op.execute("DROP INDEX IF EXISTS ix_invoices_family_id")
    op.execute("DROP TABLE IF EXISTS invoices")
    op.execute("DROP TYPE IF EXISTS invoice_status")
