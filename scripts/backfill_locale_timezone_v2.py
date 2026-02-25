"""Backfill locale/timezone v2 fields in user_profiles.

Usage:
    python scripts/backfill_locale_timezone_v2.py
    python scripts/backfill_locale_timezone_v2.py --dry-run
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.core.locale_resolution import normalize_language
from src.core.models.user import User
from src.core.models.user_profile import UserProfile


async def run_backfill(dry_run: bool = False) -> tuple[int, int]:
    """Backfill locale fields for all user profiles."""
    changed = 0
    scanned = 0
    now = datetime.now(UTC)

    async with async_session() as session:
        result = await session.execute(
            select(UserProfile, User.language).join(User, UserProfile.user_id == User.id)
        )
        rows = result.all()

        for profile, user_language in rows:
            scanned += 1
            row_changed = False

            candidate = (
                profile.notification_language
                or profile.preferred_language
                or user_language
                or "en"
            )
            normalized = normalize_language(candidate)
            if profile.notification_language != normalized:
                profile.notification_language = normalized
                row_changed = True

            if not profile.timezone_source:
                profile.timezone_source = "default"
                row_changed = True

            if profile.timezone_confidence is None:
                profile.timezone_confidence = 0
                row_changed = True

            if row_changed and profile.locale_updated_at is None:
                profile.locale_updated_at = now

            if row_changed:
                changed += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return scanned, changed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill locale/timezone v2 fields")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not commit changes; print counts only",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    scanned, changed = await run_backfill(dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"[{mode}] scanned_profiles={scanned} changed_profiles={changed}")


if __name__ == "__main__":
    asyncio.run(_main())

