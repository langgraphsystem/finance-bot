"""Add bookings and client_interactions tables for CRM/Booking agent.

Revision ID: 007
Revises: 006, 006b
Create Date: 2026-02-19
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = ("006", "006b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE booking_status AS ENUM "
        "('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE interaction_channel AS ENUM "
        "('phone', 'telegram', 'whatsapp', 'sms', 'email'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE interaction_direction AS ENUM "
        "('inbound', 'outbound'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    ))

    # Create bookings table
    op.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS bookings ("
        "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  family_id UUID NOT NULL REFERENCES families(id),"
        "  user_id UUID NOT NULL REFERENCES users(id),"
        "  contact_id UUID REFERENCES contacts(id),"
        "  title VARCHAR(255) NOT NULL,"
        "  service_type VARCHAR(100),"
        "  start_at TIMESTAMPTZ NOT NULL,"
        "  end_at TIMESTAMPTZ NOT NULL,"
        "  location VARCHAR(500),"
        "  notes TEXT,"
        "  status booking_status NOT NULL DEFAULT 'scheduled',"
        "  reminder_sent BOOLEAN DEFAULT FALSE,"
        "  confirmation_sent BOOLEAN DEFAULT FALSE,"
        "  source_channel VARCHAR(50) DEFAULT 'telegram',"
        "  external_calendar_event_id VARCHAR(255),"
        "  meta JSONB,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    ))

    # Create client_interactions table
    op.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS client_interactions ("
        "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  family_id UUID NOT NULL REFERENCES families(id),"
        "  contact_id UUID NOT NULL REFERENCES contacts(id),"
        "  channel interaction_channel NOT NULL,"
        "  direction interaction_direction NOT NULL,"
        "  content TEXT,"
        "  booking_id UUID REFERENCES bookings(id),"
        "  call_duration_seconds INTEGER,"
        "  call_recording_url VARCHAR(500),"
        "  meta JSONB,"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    ))

    # Indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_bookings_family ON bookings (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_user ON bookings (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_contact ON bookings (contact_id)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_start ON bookings (start_at)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_status ON bookings (status)",
        "CREATE INDEX IF NOT EXISTS ix_client_interactions_family "
        "ON client_interactions (family_id)",
        "CREATE INDEX IF NOT EXISTS ix_client_interactions_contact "
        "ON client_interactions (contact_id)",
        "CREATE INDEX IF NOT EXISTS ix_client_interactions_booking "
        "ON client_interactions (booking_id)",
    ]
    for idx in indexes:
        op.execute(idx)

    # RLS
    op.execute("ALTER TABLE bookings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "CREATE POLICY bookings_family_isolation ON bookings "
        "USING (family_id = current_setting('app.current_family_id')::uuid); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute("ALTER TABLE client_interactions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "CREATE POLICY client_interactions_family_isolation ON client_interactions "
        "USING (family_id = current_setting('app.current_family_id')::uuid); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS client_interactions_family_isolation "
        "ON client_interactions"
    )
    op.execute("DROP POLICY IF EXISTS bookings_family_isolation ON bookings")
    op.execute("DROP TABLE IF EXISTS client_interactions CASCADE")
    op.execute("DROP TABLE IF EXISTS bookings CASCADE")
    op.execute("DROP TYPE IF EXISTS interaction_direction")
    op.execute("DROP TYPE IF EXISTS interaction_channel")
    op.execute("DROP TYPE IF EXISTS booking_status")
