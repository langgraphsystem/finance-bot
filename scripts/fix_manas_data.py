"""One-time script: fix Manas's transaction data.

Fixes:
1. Create "Топливо" (family scope) category — missing for personal fuel
2. Recategorize 2 fuel receipts → "Топливо" + scope=family
3. Delete garbage transaction ($0, merchant "7a802802")
4. Delete 2 duplicate transactions ($100 + $5000 from Feb 24)
5. Fix Costco grocery scope: business → family
6. Create merchant mappings

Run: python scripts/fix_manas_data.py
Requires: DATABASE_URL env var.
"""

import asyncio
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

FAMILY_ID = "80ac2e59-408a-45e1-aff8-817ce04686bd"

# Transactions to fix
FUEL_TX_IDS = [
    "2f3ee6a9-9bff-4f3e-a398-11f4e6dad02a",  # DOWNERS GROVE TRIO $24.89, 8.354 gal
    "d3889765-bbbc-4d7e-b064-e3b6e92feb88",  # Costco Wholesale $25.15, 8.443 gal
]
GARBAGE_TX_ID = "fd62bd8d-b3ec-4729-a8bc-601f34cf4cfe"  # $0, merchant "7a802802"
DUPLICATE_TX_IDS = [
    "305d1dd6-53ad-4142-8545-fcf5779e65f4",  # $100 dup (created 12min after ad4330a8)
    "d5081fc2-ecf5-4d59-b0c5-13cde80cd164",  # $5000 dup (created 12min after c90d1913)
]
COSTCO_GROCERY_TX_ID = "92eb2a55-73d5-42da-81f7-210684ade596"  # $155.41 Costco groceries


async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: Set DATABASE_URL env var")
        return

    # Ensure asyncpg driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)
    async_sess = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_sess() as session:
        # ── 1. Create "Топливо" family-scope category ──
        # Check if it already exists
        existing = await session.execute(
            text("""
                SELECT id FROM categories
                WHERE family_id = :family_id AND name = 'Топливо' AND scope = 'family'
                LIMIT 1
            """),
            {"family_id": FAMILY_ID},
        )
        fuel_cat_row = existing.scalar_one_or_none()

        if fuel_cat_row:
            fuel_cat_id = str(fuel_cat_row)
            print(f"1. Category 'Топливо' (family) already exists: {fuel_cat_id}")
        else:
            fuel_cat_id = str(uuid.uuid4())
            await session.execute(
                text("""
                    INSERT INTO categories (id, family_id, name, scope, icon, is_default)
                    VALUES (:id, :family_id, 'Топливо', 'family', '⛽', false)
                """),
                {"id": fuel_cat_id, "family_id": FAMILY_ID},
            )
            print(f"1. Created category 'Топливо' (family): {fuel_cat_id}")

        # ── 2. Recategorize fuel receipts → Топливо + scope=family ──
        for tx_id in FUEL_TX_IDS:
            result = await session.execute(
                text("""
                    UPDATE transactions
                    SET category_id = :cat_id, scope = 'family'
                    WHERE id = :tx_id AND family_id = :family_id
                    RETURNING merchant, amount
                """),
                {"cat_id": fuel_cat_id, "tx_id": tx_id, "family_id": FAMILY_ID},
            )
            row = result.fetchone()
            if row:
                print(f"2. Recategorized fuel: {row.merchant} ${row.amount} → Топливо (family)")
            else:
                print(f"2. SKIP: Transaction {tx_id} not found")

        # ── 3. Delete garbage transaction ──
        result = await session.execute(
            text("""
                DELETE FROM transactions
                WHERE id = :tx_id AND family_id = :family_id
                RETURNING merchant, amount
            """),
            {"tx_id": GARBAGE_TX_ID, "family_id": FAMILY_ID},
        )
        row = result.fetchone()
        if row:
            print(f"3. Deleted garbage: merchant='{row.merchant}' amount=${row.amount}")
        else:
            print(f"3. SKIP: Garbage tx {GARBAGE_TX_ID} not found")

        # ── 4. Delete duplicate transactions ──
        for tx_id in DUPLICATE_TX_IDS:
            result = await session.execute(
                text("""
                    DELETE FROM transactions
                    WHERE id = :tx_id AND family_id = :family_id
                    RETURNING type, amount, date
                """),
                {"tx_id": tx_id, "family_id": FAMILY_ID},
            )
            row = result.fetchone()
            if row:
                print(f"4. Deleted duplicate: {row.type} ${row.amount} ({row.date})")
            else:
                print(f"4. SKIP: Duplicate tx {tx_id} not found")

        # ── 5. Fix Costco grocery scope → family ──
        result = await session.execute(
            text("""
                UPDATE transactions
                SET scope = 'family'
                WHERE id = :tx_id AND family_id = :family_id
                RETURNING merchant, amount, scope
            """),
            {"tx_id": COSTCO_GROCERY_TX_ID, "family_id": FAMILY_ID},
        )
        row = result.fetchone()
        if row:
            print(f"5. Fixed scope: {row.merchant} ${row.amount} → {row.scope}")
        else:
            print(f"5. SKIP: Costco grocery tx {COSTCO_GROCERY_TX_ID} not found")

        # ── 6. Create merchant mappings ──
        # Costco fuel → Топливо (family) — small fills at Costco gas station
        # Note: Costco grocery receipts don't have gallons, so they won't match fuel logic
        mappings = [
            ("costco", fuel_cat_id, "family"),  # Costco gas → family fuel
            ("downers grove trio", fuel_cat_id, "family"),  # Local gas station
        ]
        created = 0
        for pattern, cat_id, scope in mappings:
            exists = await session.execute(
                text("""
                    SELECT 1 FROM merchant_mappings
                    WHERE family_id = :family_id AND merchant_pattern = :pattern
                    LIMIT 1
                """),
                {"family_id": FAMILY_ID, "pattern": pattern},
            )
            if exists.scalar_one_or_none():
                print(f"6. Mapping '{pattern}' already exists, skipping")
                continue
            await session.execute(
                text("""
                    INSERT INTO merchant_mappings
                        (id, family_id, merchant_pattern, category_id, scope)
                    VALUES (:id, :family_id, :pattern, :category_id, :scope)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "family_id": FAMILY_ID,
                    "pattern": pattern,
                    "category_id": cat_id,
                    "scope": scope,
                },
            )
            created += 1
        print(f"6. Created {created} merchant mappings")

        await session.commit()
        print("\nDone! All changes committed.")

        # ── Verify ──
        result = await session.execute(
            text("""
                SELECT t.id, t.type, t.amount, t.merchant, t.scope, c.name as category
                FROM transactions t
                JOIN categories c ON c.id = t.category_id
                WHERE t.family_id = :family_id
                ORDER BY t.created_at
            """),
            {"family_id": FAMILY_ID},
        )
        rows = result.fetchall()
        print(f"\nVerification — {len(rows)} transactions remaining:")
        for row in rows:
            print(
                f"  {row.type:7s} ${row.amount:>10s} | {row.scope:8s} | "
                f"{row.category:20s} | {row.merchant or '—'}"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
