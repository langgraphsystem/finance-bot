"""Centralized timezone detection and update helpers.

Confidence hierarchy (higher = more trusted, never overwrite with lower):
  user_set(100) > mini_app_js(90) > slack_api(85) > city_geocode(80)
  > phone_number_single(80) > geo_ip(70) > phone_number_multi(40)
  > channel_hint(30) > default(0)
"""

import logging
import uuid as _uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update

from src.core.db import async_session
from src.core.models.user import User
from src.core.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

TIMEZONE_CONFIDENCE: dict[str, int] = {
    "user_set": 100,
    "mini_app_js": 90,
    "slack_api": 85,
    "city_geocode": 80,
    "phone_number_single": 80,
    "geo_ip": 70,
    "phone_number_multi": 40,
    "channel_hint": 30,
    "default": 0,
}

# Most-populous timezone per multi-zone country (used as fallback)
_COUNTRY_DEFAULT_TZ: dict[int, str] = {
    1: "America/New_York",    # US/Canada — Eastern most populous
    7: "Europe/Moscow",       # Russia
    61: "Australia/Sydney",   # Australia
    55: "America/Sao_Paulo",  # Brazil
    86: "Asia/Shanghai",      # China
    91: "Asia/Kolkata",       # India
}


def validate_timezone(tz: str) -> bool:
    """Check if timezone string is a valid IANA timezone."""
    if not isinstance(tz, str) or not tz:
        return False
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return False


async def _ensure_user_profile(
    session,
    user_id: str,
    timezone: str,
    source: str,
    confidence: int,
) -> bool:
    """Create a minimal profile when a legacy user is missing one."""
    user_uuid = _uuid.UUID(user_id)
    existing = await session.scalar(
        select(UserProfile.id).where(UserProfile.user_id == user_uuid).limit(1)
    )
    if existing is not None:
        return False

    user = await session.scalar(select(User).where(User.id == user_uuid))
    if not user:
        logger.warning("Cannot create missing user_profile: no user row for %s", user_id)
        return False

    session.add(
        UserProfile(
            user_id=user.id,
            family_id=user.family_id,
            display_name=user.name,
            timezone=timezone,
            timezone_source=source,
            timezone_confidence=confidence,
            preferred_language=getattr(user, "language", "en") or "en",
            locale_updated_at=datetime.now(UTC),
        )
    )
    await session.flush()
    logger.info("Created missing user_profile for %s", user_id)
    return True


async def maybe_update_timezone(
    user_id: str,
    timezone: str,
    source: str,
    confidence: int | None = None,
) -> bool:
    """Update timezone only if the new source has higher confidence.

    Equal confidence is intentionally stable: the existing source wins.
    Returns True if updated/created, False if skipped or invalid.
    """
    if not validate_timezone(timezone):
        logger.warning("Invalid timezone %r for user %s", timezone, user_id)
        return False

    if confidence is None:
        confidence = TIMEZONE_CONFIDENCE.get(source, 0)

    try:
        async with async_session() as session:
            created = await _ensure_user_profile(
                session,
                user_id=user_id,
                timezone=timezone,
                source=source,
                confidence=confidence,
            )
            result = await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == _uuid.UUID(user_id))
                .where(UserProfile.timezone_confidence < confidence)
                .values(
                    timezone=timezone,
                    timezone_source=source,
                    timezone_confidence=confidence,
                    locale_updated_at=datetime.now(UTC),
                )
            )
            if result.rowcount > 0:
                await session.commit()
                logger.info(
                    "Timezone updated: user=%s tz=%s source=%s confidence=%d",
                    user_id, timezone, source, confidence,
                )
                return True
            if created:
                await session.commit()
                return True
            await session.rollback()
            return False
    except Exception:
        logger.debug("Failed to update timezone for user %s", user_id, exc_info=True)
        return False


def timezone_from_phone(phone_e164: str) -> tuple[str | None, int]:
    """Extract timezone from E.164 phone number.

    Returns (timezone_iana, confidence).
    Confidence: 80 if single zone, 40 if multiple zones.
    """
    try:
        import phonenumbers
        from phonenumbers import timezone as pn_tz
    except ImportError:
        logger.debug("phonenumbers not installed, skipping phone timezone detection")
        return None, 0

    try:
        if not phone_e164.startswith("+"):
            phone_e164 = f"+{phone_e164}"
        number = phonenumbers.parse(phone_e164, None)
        zones = pn_tz.time_zones_for_number(number)
    except Exception:
        return None, 0

    if not zones:
        return None, 0

    zone_list = list(zones)
    if len(zone_list) == 1:
        return zone_list[0], 80

    # Multiple zones: pick most populous for that country
    country_code = number.country_code
    default_tz = _COUNTRY_DEFAULT_TZ.get(country_code)
    if default_tz and default_tz in zone_list:
        return default_tz, 40

    return zone_list[0], 40
