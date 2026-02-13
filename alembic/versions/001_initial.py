"""Initial schema -- all 13 tables.

Revision ID: 001
Revises:
Create Date: 2026-02-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, UUID, JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum types (idempotent via DO/EXCEPTION) ────────────────
    _enums = {
        "transaction_type": "'income', 'expense'",
        "scope": "'business', 'family', 'personal'",
        "user_role": "'owner', 'member'",
        "document_type": "'receipt', 'invoice', 'rate_confirmation', 'fuel_receipt', 'other'",
        "load_status": "'pending', 'delivered', 'paid', 'overdue'",
        "message_role": "'user', 'assistant'",
        "conversation_state": "'onboarding', 'normal', 'correcting', 'awaiting_confirm'",
        "payment_frequency": "'weekly', 'monthly', 'quarterly', 'yearly'",
        "budget_period": "'weekly', 'monthly'",
    }
    for name, values in _enums.items():
        op.execute(sa.text(
            f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({values}); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        ))

    # Reference existing types — postgresql.ENUM with create_type=False
    transaction_type = ENUM("income", "expense", name="transaction_type", create_type=False)
    scope = ENUM("business", "family", "personal", name="scope", create_type=False)
    user_role = ENUM("owner", "member", name="user_role", create_type=False)
    document_type = ENUM(
        "receipt", "invoice", "rate_confirmation", "fuel_receipt", "other",
        name="document_type", create_type=False,
    )
    load_status = ENUM("pending", "delivered", "paid", "overdue", name="load_status", create_type=False)
    message_role = ENUM("user", "assistant", name="message_role", create_type=False)
    conversation_state = ENUM(
        "onboarding", "normal", "correcting", "awaiting_confirm",
        name="conversation_state", create_type=False,
    )
    payment_frequency = ENUM("weekly", "monthly", "quarterly", "yearly", name="payment_frequency", create_type=False)
    budget_period = ENUM("weekly", "monthly", name="budget_period", create_type=False)

    # 1. families
    op.create_table(
        "families",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("invite_code", sa.String(20), nullable=False, unique=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="UTC"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 2. users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("business_type", sa.String(100), nullable=True),
        sa.Column("language", sa.String(5), nullable=False, server_default="ru"),
        sa.Column("onboarded", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 3. categories
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope", scope, nullable=False),
        sa.Column("icon", sa.String(10), nullable=False, server_default=sa.text("'\\xF0\\x9F\\x93\\xA6'")),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("business_type", sa.String(100), nullable=True),
    )

    # 4. documents (must come before transactions which reference it)
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", document_type, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("ocr_model", sa.String(50), nullable=True),
        sa.Column("ocr_raw", JSONB, nullable=True),
        sa.Column("ocr_parsed", JSONB, nullable=True),
        sa.Column("ocr_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("ocr_fallback_used", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ocr_latency_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 5. transactions
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("type", transaction_type, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("original_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("original_currency", sa.String(10), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("merchant", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("scope", scope, nullable=False),
        sa.Column("state", sa.String(50), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=False, server_default=sa.text("1.0")),
        sa.Column("is_corrected", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 6. merchant_mappings
    op.create_table(
        "merchant_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("merchant_pattern", sa.String(255), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("scope", scope, nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0.5")),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    )

    # 7. loads
    op.create_table(
        "loads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("broker", sa.String(255), nullable=False),
        sa.Column("origin", sa.String(255), nullable=False),
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("ref_number", sa.String(100), nullable=True),
        sa.Column("pickup_date", sa.Date, nullable=False),
        sa.Column("delivery_date", sa.Date, nullable=True),
        sa.Column("status", load_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("paid_date", sa.Date, nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
    )

    # 8. conversation_messages
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("entities", JSONB, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 9. user_context
    op.create_table(
        "user_context",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("last_transaction_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "last_category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("categories.id"),
            nullable=True,
        ),
        sa.Column("last_merchant", sa.String(255), nullable=True),
        sa.Column("pending_confirmation", JSONB, nullable=True),
        sa.Column(
            "conversation_state",
            conversation_state,
            nullable=False,
            server_default=sa.text("'normal'"),
        ),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("message_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 10. session_summaries
    op.create_table(
        "session_summaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("message_count", sa.Integer, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 11. audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("old_data", JSONB, nullable=True),
        sa.Column("new_data", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 12. recurring_payments
    op.create_table(
        "recurring_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("frequency", payment_frequency, nullable=False),
        sa.Column("next_date", sa.Date, nullable=False),
        sa.Column("auto_record", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 13. budgets
    op.create_table(
        "budgets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", UUID(as_uuid=True), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("scope", scope, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("period", budget_period, nullable=False),
        sa.Column("alert_at", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0.8")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── Indexes ─────────────────────────────────────────────────
    op.create_index("ix_transactions_family_date", "transactions", ["family_id", "date"])
    op.create_index("ix_transactions_family_category", "transactions", ["family_id", "category_id"])
    op.create_index("ix_transactions_user", "transactions", ["user_id"])
    op.create_index("ix_transactions_family_type", "transactions", ["family_id", "type"])

    op.create_index("ix_conversation_messages_user_created", "conversation_messages", ["user_id", "created_at"])
    op.create_index("ix_conversation_messages_family", "conversation_messages", ["family_id"])

    op.create_index("ix_merchant_mappings_family_pattern", "merchant_mappings", ["family_id", "merchant_pattern"])

    op.create_index("ix_audit_log_family_created", "audit_log", ["family_id", "created_at"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_audit_log_family_created", table_name="audit_log")
    op.drop_index("ix_merchant_mappings_family_pattern", table_name="merchant_mappings")
    op.drop_index("ix_conversation_messages_family", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_user_created", table_name="conversation_messages")
    op.drop_index("ix_transactions_family_type", table_name="transactions")
    op.drop_index("ix_transactions_user", table_name="transactions")
    op.drop_index("ix_transactions_family_category", table_name="transactions")
    op.drop_index("ix_transactions_family_date", table_name="transactions")

    # Drop tables in reverse dependency order
    op.drop_table("budgets")
    op.drop_table("recurring_payments")
    op.drop_table("audit_log")
    op.drop_table("session_summaries")
    op.drop_table("user_context")
    op.drop_table("conversation_messages")
    op.drop_table("loads")
    op.drop_table("merchant_mappings")
    op.drop_table("transactions")
    op.drop_table("documents")
    op.drop_table("categories")
    op.drop_table("users")
    op.drop_table("families")

    # Drop enum types
    for name in (
        "budget_period",
        "payment_frequency",
        "conversation_state",
        "message_role",
        "load_status",
        "document_type",
        "user_role",
        "scope",
        "transaction_type",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
