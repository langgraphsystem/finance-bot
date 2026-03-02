"""One-time script: migrate documents with inline/pending storage to Supabase Storage.

Finds all documents where storage_path starts with 'inline:' or equals 'pending',
decodes the image_b64 from ocr_raw, uploads to Supabase Storage, and updates storage_path.

Run: python scripts/migrate_inline_docs.py
Requires: DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY env vars.
"""

import asyncio
import base64
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def main():
    db_url = os.environ.get("DATABASE_URL")
    supa_url = os.environ.get("SUPABASE_URL")
    supa_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not db_url:
        print("ERROR: Set DATABASE_URL env var")
        return
    if not supa_url or not supa_key:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars")
        return

    # Ensure asyncpg driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    from supabase import create_client

    supa = create_client(supa_url, supa_key)

    # Ensure the 'documents' bucket exists
    bucket = "documents"
    try:
        supa.storage.get_bucket(bucket)
        print(f"Bucket '{bucket}' exists")
    except Exception:
        print(f"Creating bucket '{bucket}'...")
        supa.storage.create_bucket(bucket, options={"public": False})
        print(f"Bucket '{bucket}' created")

    engine = create_async_engine(db_url, echo=False)
    async_sess = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_sess() as session:
        # Find all documents with inline or pending storage
        result = await session.execute(
            text("""
                SELECT id, family_id, storage_path,
                       ocr_raw->>'image_b64' as image_b64,
                       ocr_raw->>'mime_type' as mime_type
                FROM documents
                WHERE storage_path LIKE 'inline:%' OR storage_path = 'pending'
                ORDER BY created_at
            """)
        )
        rows = result.fetchall()

        if not rows:
            print("No documents to migrate.")
            return

        print(f"Found {len(rows)} documents to migrate\n")

        migrated = 0
        skipped = 0

        for row in rows:
            doc_id = row.id
            family_id = str(row.family_id)
            image_b64 = row.image_b64
            mime_type = row.mime_type or "image/jpeg"

            if not image_b64:
                print(f"  SKIP {doc_id}: no image_b64 in ocr_raw")
                skipped += 1
                continue

            # Decode base64 image
            try:
                image_bytes = base64.b64decode(image_b64)
            except Exception as e:
                print(f"  SKIP {doc_id}: failed to decode base64: {e}")
                skipped += 1
                continue

            # Determine file extension from mime_type
            ext_map = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "application/pdf": "pdf",
                "image/webp": "webp",
            }
            ext = ext_map.get(mime_type, mime_type.split("/")[-1] if "/" in mime_type else "bin")

            # Upload to Supabase Storage
            unique_name = f"{uuid.uuid4().hex[:8]}_doc_{str(doc_id)[:8]}.{ext}"
            path = f"{family_id}/{unique_name}"
            bucket = "documents"

            try:
                supa.storage.from_(bucket).upload(
                    path,
                    image_bytes,
                    file_options={"content-type": mime_type},
                )
                storage_path = f"{bucket}/{path}"
            except Exception as e:
                print(f"  FAIL {doc_id}: upload failed: {e}")
                skipped += 1
                continue

            # Update storage_path in DB
            await session.execute(
                text("""
                    UPDATE documents
                    SET storage_path = :storage_path
                    WHERE id = :doc_id
                """),
                {"storage_path": storage_path, "doc_id": str(doc_id)},
            )

            migrated += 1
            print(f"  OK   {doc_id}: {row.storage_path} -> {storage_path}")

        await session.commit()
        print(f"\nDone! Migrated: {migrated}, Skipped: {skipped}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
