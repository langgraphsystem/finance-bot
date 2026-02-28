"""Supabase Storage utilities for document upload/download."""

import logging
import uuid as uuid_mod

from src.core.config import settings

logger = logging.getLogger(__name__)


async def upload_document(
    file_bytes: bytes,
    family_id: str,
    filename: str,
    mime_type: str = "application/octet-stream",
    bucket: str = "documents",
) -> str:
    """Upload document bytes to Supabase Storage.

    Returns the storage path (bucket/family_id/unique_filename).
    Falls back to 'pending' if Supabase is not configured or upload fails.
    """
    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning("Supabase not configured — storage_path will be 'pending'")
        return "pending"

    try:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_service_key)

        # Generate unique path to avoid collisions
        unique_name = f"{uuid_mod.uuid4().hex[:8]}_{filename}"
        path = f"{family_id}/{unique_name}"

        client.storage.from_(bucket).upload(
            path,
            file_bytes,
            file_options={"content-type": mime_type},
        )

        return f"{bucket}/{path}"
    except Exception as e:
        logger.warning("Supabase upload failed: %s — falling back to pending", e)
        return "pending"


async def download_document(storage_path: str) -> bytes | None:
    """Download document bytes from Supabase Storage.

    Returns None if not found, path is 'pending', or Supabase is not configured.
    """
    if not storage_path or storage_path == "pending":
        return None
    if not settings.supabase_url or not settings.supabase_service_key:
        return None

    try:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_service_key)
        bucket, _, file_path = storage_path.partition("/")
        data = client.storage.from_(bucket).download(file_path)
        return data
    except Exception as e:
        logger.warning("Supabase download failed for %s: %s", storage_path, e)
        return None


async def delete_document(storage_path: str) -> bool:
    """Delete document from Supabase Storage.

    Returns True if the delete request was sent successfully, False otherwise.
    """
    if not storage_path or storage_path == "pending":
        return False
    if not settings.supabase_url or not settings.supabase_service_key:
        return False

    try:
        from supabase import create_client

        client = create_client(settings.supabase_url, settings.supabase_service_key)
        bucket, _, file_path = storage_path.partition("/")
        client.storage.from_(bucket).remove([file_path])
        return True
    except Exception as e:
        logger.warning("Supabase delete failed for %s: %s", storage_path, e)
        return False
