"""Sheets sync cron — pushes data to Google Sheets every hour."""

import logging

from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "0 * * * *"}])
async def sync_sheets_hourly() -> None:
    """Sync all active sheet configs."""
    from sqlalchemy import text

    from src.core.db import async_session

    logger.info("Starting hourly sheets sync")
    try:
        async with async_session() as session:
            result = await session.execute(
                text("SELECT * FROM sheet_sync_configs WHERE is_active = true")
            )
            configs = result.all()
    except Exception as e:
        logger.error("Failed to fetch sync configs: %s", e)
        return

    synced = 0
    for config in configs:
        try:
            from src.tools.google_workspace import get_composio_client

            # Find a user in this family with Google Sheets access
            async with async_session() as session:
                user_result = await session.execute(
                    text("""
                        SELECT u.id FROM users u
                        JOIN oauth_tokens ot ON u.id = ot.user_id
                        WHERE u.family_id = :fid AND ot.provider = 'google'
                        LIMIT 1
                    """),
                    {"fid": str(config.family_id)},
                )
                user_row = user_result.first()

            if not user_row:
                continue

            client = await get_composio_client(str(user_row.id))
            rows = await _fetch_data(str(config.family_id), config.sync_scope)
            if not rows:
                continue

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
                await session.execute(
                    text("""
                        UPDATE sheet_sync_configs SET last_synced_at = now()
                        WHERE id = :id
                    """),
                    {"id": str(config.id)},
                )
                await session.commit()
            synced += 1
        except Exception as e:
            logger.warning("Failed to sync config %s: %s", config.id, e)

    logger.info("Sheets sync complete: %d/%d configs", synced, len(configs))


async def _fetch_data(family_id: str, scope: str) -> list[list[str]]:
    """Fetch data rows for the given scope."""
    from sqlalchemy import text

    from src.core.db import async_session

    async with async_session() as session:
        if scope == "expenses":
            result = await session.execute(
                text("""
                    SELECT date, merchant, category, amount, description
                    FROM transactions
                    WHERE family_id = :fid AND type = 'expense'
                      AND date >= date_trunc('month', CURRENT_DATE)
                    ORDER BY date DESC
                    LIMIT 10000
                """),
                {"fid": family_id},
            )
            rows = result.all()
            header = ["Date", "Merchant", "Category", "Amount", "Description"]
            return [header] + [
                [
                    str(r.date),
                    r.merchant or "",
                    r.category or "",
                    str(r.amount),
                    r.description or "",
                ]
                for r in rows
            ]
        elif scope == "tasks":
            result = await session.execute(
                text("""
                    SELECT title, status, deadline, created_at
                    FROM tasks WHERE family_id = :fid
                    ORDER BY created_at DESC LIMIT 1000
                """),
                {"fid": family_id},
            )
            rows = result.all()
            header = ["Title", "Status", "Due Date", "Created"]
            return [header] + [
                [
                    r.title,
                    r.status or "",
                    str(r.deadline or ""),
                    str(r.created_at or ""),
                ]
                for r in rows
            ]
        elif scope == "contacts":
            result = await session.execute(
                text("""
                    SELECT name, phone, email, role, notes
                    FROM contacts WHERE family_id = :fid
                    ORDER BY name LIMIT 1000
                """),
                {"fid": family_id},
            )
            rows = result.all()
            header = ["Name", "Phone", "Email", "Role", "Notes"]
            return [header] + [
                [r.name, r.phone or "", r.email or "", r.role or "", r.notes or ""]
                for r in rows
            ]
    return []
