"""Google Sheets sync cron task — pushes latest data to active sheet configs.

Runs hourly. For each active SheetSyncConfig, fetches the associated user,
builds a minimal context, and pushes current data to the Google Sheet.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.sheet_sync_config import SheetSyncConfig
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "0 * * * *"}])  # Every hour
async def sync_sheets_hourly() -> None:
    """Push latest data to all active Google Sheet sync configs."""
    async with async_session() as session:
        result = await session.execute(
            select(SheetSyncConfig).where(SheetSyncConfig.is_active.is_(True))
        )
        configs = list(result.scalars().all())

    if not configs:
        return

    logger.info("Sheets sync: processing %d active configs", len(configs))

    for config in configs:
        try:
            await _sync_single_config(config)
        except Exception as e:
            logger.warning(
                "Sheets sync failed for config %s (family %s): %s",
                config.id,
                config.family_id,
                e,
            )


async def _sync_single_config(config: SheetSyncConfig) -> None:
    """Sync a single sheet config with latest data."""
    from src.core.google_auth import get_google_client, has_google_connection

    # Find a user in this family to get Google credentials
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.family_id == config.family_id).limit(1)
        )
        user = result.scalar_one_or_none()

    if not user:
        logger.debug("No user found for family %s, skipping sync", config.family_id)
        return

    user_id = str(user.id)
    if not await has_google_connection(user_id, service="sheets"):
        logger.debug("No Google Sheets connection for user %s, skipping", user_id)
        return

    client = await get_google_client(user_id)
    if not client:
        return

    # Build a minimal context for data fetching
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id=user_id,
        family_id=str(config.family_id),
        role="owner",
        language="en",
        currency="USD",
        categories=[],
        merchant_mappings=[],
    )

    # Fetch data based on sync scope
    from src.skills.sheets_sync.handler import SheetsSyncSkill

    skill = SheetsSyncSkill()
    if config.sync_scope == "expenses":
        rows = await skill._fetch_expenses(ctx)
    elif config.sync_scope == "tasks":
        rows = await skill._fetch_tasks(ctx)
    elif config.sync_scope == "contacts":
        rows = await skill._fetch_contacts(ctx)
    else:
        return

    if not rows:
        return

    # Clear existing data and push fresh
    await client.execute_action(
        "GOOGLESHEETS_BATCH_UPDATE",
        params={
            "spreadsheet_id": config.spreadsheet_id,
            "range": f"{config.sheet_name}!A1",
            "values": rows,
        },
    )

    # Update last_synced_at
    async with async_session() as session:
        result = await session.execute(
            select(SheetSyncConfig).where(SheetSyncConfig.id == config.id)
        )
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.last_synced_at = datetime.now(UTC)
            await session.commit()

    logger.info(
        "Synced %d rows to sheet %s (scope: %s)",
        len(rows),
        config.spreadsheet_id,
        config.sync_scope,
    )
