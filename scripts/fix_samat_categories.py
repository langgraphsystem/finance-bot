"""One-time script: fix Samat's diesel transaction categories + create merchant mappings.

Run: python scripts/fix_samat_categories.py
Requires DATABASE_URL env var (production Supabase).
"""

import asyncio
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

FAMILY_ID = "7cf7c7b6-339f-4b54-a4e1-d20cbcfee7e3"
DIESEL_CATEGORY_ID = "9cfad328-5a1c-45a4-bbc3-42f828255228"

FUEL_MERCHANT_PATTERNS = ["pilot", "loves", "flying j", "ta ", "petro"]


async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: Set DATABASE_URL env var")
        return

    # Ensure asyncpg driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Re-categorize diesel transactions
        result = await session.execute(
            text("""
                UPDATE transactions
                SET category_id = :diesel_cat
                WHERE family_id = :family_id
                  AND scope = 'business'
                  AND meta->>'gallons' IS NOT NULL
                RETURNING id, merchant, amount
            """),
            {"diesel_cat": DIESEL_CATEGORY_ID, "family_id": FAMILY_ID},
        )
        updated = result.fetchall()
        print(f"Updated {len(updated)} transactions to 'Дизель':")
        for row in updated:
            print(f"  - {row.merchant}: ${row.amount} (id: {row.id})")

        # 2. Create merchant mappings for fuel stops (skip if already exists)
        created = 0
        for pattern in FUEL_MERCHANT_PATTERNS:
            exists = await session.execute(
                text("""
                    SELECT 1 FROM merchant_mappings
                    WHERE family_id = :family_id AND merchant_pattern = :pattern
                    LIMIT 1
                """),
                {"family_id": FAMILY_ID, "pattern": pattern},
            )
            if exists.scalar_one_or_none():
                print(f"  Mapping '{pattern}' already exists, skipping")
                continue
            await session.execute(
                text("""
                    INSERT INTO merchant_mappings
                        (id, family_id, merchant_pattern, category_id, scope)
                    VALUES (:id, :family_id, :pattern, :category_id, 'business')
                """),
                {
                    "id": str(uuid.uuid4()),
                    "family_id": FAMILY_ID,
                    "pattern": pattern,
                    "category_id": DIESEL_CATEGORY_ID,
                },
            )
            created += 1
        print(f"\nCreated {created} merchant mappings for fuel stops")

        await session.commit()
        print("\nDone! All changes committed.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
