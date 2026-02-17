"""Add multi-domain tables: contacts, tasks, email_cache, calendar_cache,
monitors, user_profiles, usage_logs, subscriptions.

Revision ID: 005
Revises: 004
Create Date: 2026-02-17
"""

import sqlalchemy as sa

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create new enum types ──────────────────────────────────

    for enum_sql in [
        (
            "CREATE TYPE task_status AS ENUM "
            "('pending', 'in_progress', 'done', 'cancelled')"
        ),
        (
            "CREATE TYPE task_priority AS ENUM "
            "('low', 'medium', 'high', 'urgent')"
        ),
        (
            "CREATE TYPE contact_role AS ENUM "
            "('client', 'vendor', 'partner', 'friend', 'family', 'doctor', 'other')"
        ),
        (
            "CREATE TYPE monitor_type AS ENUM "
            "('price', 'news', 'competitor', 'exchange_rate')"
        ),
        (
            "CREATE TYPE subscription_status AS ENUM "
            "('active', 'past_due', 'cancelled', 'trial')"
        ),
        (
            "CREATE TYPE channel_type AS ENUM "
            "('telegram', 'whatsapp', 'slack', 'sms')"
        ),
    ]:
        op.execute(
            sa.text(
                f"DO $$ BEGIN {enum_sql}; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
            )
        )

    # ── 2. Create contacts table ──────────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS contacts ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  name VARCHAR(255) NOT NULL,"
            "  phone VARCHAR(50),"
            "  email VARCHAR(255),"
            "  role contact_role NOT NULL DEFAULT 'other',"
            "  company VARCHAR(255),"
            "  tags JSONB,"
            "  notes TEXT,"
            "  last_contact_at TIMESTAMPTZ,"
            "  next_followup_at TIMESTAMPTZ,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 3. Create tasks table ─────────────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  title VARCHAR(500) NOT NULL,"
            "  description TEXT,"
            "  status task_status NOT NULL DEFAULT 'pending',"
            "  priority task_priority NOT NULL DEFAULT 'medium',"
            "  due_at TIMESTAMPTZ,"
            "  reminder_at TIMESTAMPTZ,"
            "  completed_at TIMESTAMPTZ,"
            "  assigned_to UUID REFERENCES contacts(id),"
            "  domain VARCHAR(50),"
            "  source_message_id VARCHAR(255),"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 4. Create email_cache table ───────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS email_cache ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  gmail_id VARCHAR(255) UNIQUE NOT NULL,"
            "  thread_id VARCHAR(255),"
            "  from_email VARCHAR(255),"
            "  to_emails JSONB,"
            "  subject VARCHAR(1000),"
            "  snippet TEXT,"
            "  is_read BOOLEAN DEFAULT false,"
            "  is_important BOOLEAN DEFAULT false,"
            "  followup_needed BOOLEAN DEFAULT false,"
            "  received_at TIMESTAMPTZ,"
            "  labels JSONB,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 5. Create calendar_cache table ────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS calendar_cache ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  google_event_id VARCHAR(255) UNIQUE NOT NULL,"
            "  calendar_id VARCHAR(255) DEFAULT 'primary',"
            "  title VARCHAR(500),"
            "  description TEXT,"
            "  start_at TIMESTAMPTZ,"
            "  end_at TIMESTAMPTZ,"
            "  attendees JSONB,"
            "  location VARCHAR(500),"
            "  prep_notes TEXT,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 6. Create monitors table ──────────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS monitors ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  type monitor_type NOT NULL,"
            "  name VARCHAR(255) NOT NULL,"
            "  config JSONB,"
            "  check_interval_minutes INTEGER DEFAULT 60,"
            "  last_value JSONB,"
            "  is_active BOOLEAN DEFAULT true,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 7. Create user_profiles table ─────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS user_profiles ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id) UNIQUE,"
            "  display_name VARCHAR(255),"
            "  timezone VARCHAR(50) DEFAULT 'America/New_York',"
            "  preferred_language VARCHAR(10) DEFAULT 'en',"
            "  occupation VARCHAR(255),"
            "  tone_preference VARCHAR(50) DEFAULT 'friendly',"
            "  response_length VARCHAR(20) DEFAULT 'concise',"
            "  active_hours_start INTEGER DEFAULT 8,"
            "  active_hours_end INTEGER DEFAULT 22,"
            "  learned_patterns JSONB,"
            "  bio TEXT,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 8. Create usage_logs table ────────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS usage_logs ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id),"
            "  user_id UUID NOT NULL REFERENCES users(id),"
            "  domain VARCHAR(50),"
            "  skill VARCHAR(100),"
            "  model VARCHAR(100),"
            "  tokens_input INTEGER DEFAULT 0,"
            "  tokens_output INTEGER DEFAULT 0,"
            "  cost_usd NUMERIC(10,6) DEFAULT 0,"
            "  duration_ms INTEGER DEFAULT 0,"
            "  success BOOLEAN DEFAULT true,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 9. Create subscriptions table ─────────────────────────────
    op.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS subscriptions ("
            "  id UUID PRIMARY KEY,"
            "  family_id UUID NOT NULL REFERENCES families(id) UNIQUE,"
            "  stripe_customer_id VARCHAR(255),"
            "  stripe_subscription_id VARCHAR(255),"
            "  plan VARCHAR(50) DEFAULT 'trial',"
            "  status subscription_status NOT NULL DEFAULT 'trial',"
            "  trial_ends_at TIMESTAMPTZ,"
            "  current_period_end TIMESTAMPTZ,"
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
    )

    # ── 10. Indexes ───────────────────────────────────────────────
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_contacts_family ON contacts (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_contacts_name ON contacts (family_id, name)",
        "CREATE INDEX IF NOT EXISTS ix_contacts_followup ON contacts (next_followup_at) WHERE next_followup_at IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_tasks_family ON tasks (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (family_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks (due_at) WHERE due_at IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_tasks_reminder ON tasks (reminder_at) WHERE reminder_at IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_email_cache_family ON email_cache (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_email_cache_thread ON email_cache (thread_id)",
        "CREATE INDEX IF NOT EXISTS ix_email_cache_received ON email_cache (family_id, received_at)",
        "CREATE INDEX IF NOT EXISTS ix_calendar_cache_family ON calendar_cache (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_calendar_cache_time ON calendar_cache (family_id, start_at)",
        "CREATE INDEX IF NOT EXISTS ix_monitors_family ON monitors (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_monitors_active ON monitors (is_active) WHERE is_active = true",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_family ON usage_logs (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_created ON usage_logs (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_usage_logs_domain ON usage_logs (family_id, domain)",
    ]
    for idx in indexes:
        op.execute(idx)

    # ── 11. Enable RLS on all new tables ──────────────────────────
    tables = [
        "contacts",
        "tasks",
        "email_cache",
        "calendar_cache",
        "monitors",
        "user_profiles",
        "usage_logs",
        "subscriptions",
    ]
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"DO $$ BEGIN "
            f"CREATE POLICY {table}_family_isolation ON {table} "
            f"USING (family_id = current_setting('app.current_family_id')::uuid); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )


def downgrade() -> None:
    # Drop RLS policies
    tables = [
        "subscriptions",
        "usage_logs",
        "user_profiles",
        "monitors",
        "calendar_cache",
        "email_cache",
        "tasks",
        "contacts",
    ]
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_family_isolation ON {table}")

    # Drop tables (reverse order due to FK dependencies)
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop enum types
    enums = [
        "channel_type",
        "subscription_status",
        "monitor_type",
        "contact_role",
        "task_priority",
        "task_status",
    ]
    for enum_name in enums:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
