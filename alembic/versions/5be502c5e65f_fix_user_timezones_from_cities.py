"""fix_user_timezones_from_cities

Revision ID: 5be502c5e65f
Revises: 013
Create Date: 2026-02-27 14:04:30.692787

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5be502c5e65f'
down_revision: str | None = '013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fix Schaumburg (Chicago suburb) → America/Chicago
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'America/Chicago', timezone_source = 'city_geocode', "
        "timezone_confidence = 80 "
        "WHERE city = 'Schaumburg'"
    )
    # Fix Chicago → America/Chicago
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'America/Chicago', timezone_source = 'city_geocode', "
        "timezone_confidence = 80 "
        "WHERE city = 'Chicago'"
    )
    # Fix Bishkek / Kyrgyzstan → Asia/Bishkek
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'Asia/Bishkek', timezone_source = 'city_geocode', "
        "timezone_confidence = 80 "
        "WHERE city IN ('Bishkek', 'Kyrgyzstan')"
    )


def downgrade() -> None:
    # Revert to Europe/Moscow (original channel_hint values)
    op.execute(
        "UPDATE user_profiles "
        "SET timezone = 'Europe/Moscow', timezone_source = 'channel_hint', "
        "timezone_confidence = 30 "
        "WHERE city IN ('Schaumburg', 'Chicago', 'Bishkek', 'Kyrgyzstan')"
    )
