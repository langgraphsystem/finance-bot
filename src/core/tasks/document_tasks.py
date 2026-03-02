"""Scheduled document maintenance tasks (Taskiq cron)."""

import logging
from datetime import date, timedelta

from sqlalchemy import and_, cast, delete, select
from sqlalchemy.dialects.postgresql import DATE

from src.core.db import async_session, rls_session
from src.core.models.document import Document
from src.core.models.enums import DocumentType
from src.core.models.family import Family
from src.core.request_context import reset_family_context, set_family_context
from src.core.tasks.broker import broker
from src.tools.storage import delete_document

logger = logging.getLogger(__name__)


@broker.task()
async def async_embed_document(document_id: str) -> int:
    """Background task: chunk and embed a document for semantic search."""
    from src.core.memory.document_vectors import embed_document

    return await embed_document(document_id)


@broker.task(schedule=[{"cron": "30 3 * * *"}])  # Daily at 03:30 UTC
async def batch_embed_documents() -> None:
    """Embed documents that have extracted_text but no embeddings yet."""
    from sqlalchemy import text as sql_text

    async with async_session() as session:
        result = await session.execute(
            sql_text("""
                SELECT d.id FROM documents d
                WHERE d.extracted_text IS NOT NULL
                  AND length(d.extracted_text) > 20
                  AND NOT EXISTS (
                      SELECT 1 FROM document_embeddings de
                      WHERE de.document_id = d.id
                  )
                LIMIT 50
            """)
        )
        doc_ids = [str(row[0]) for row in result.fetchall()]

    for doc_id in doc_ids:
        try:
            await async_embed_document.kiq(doc_id)
        except Exception as e:
            logger.error("Failed to queue embedding for %s: %s", doc_id, e)

    if doc_ids:
        logger.info("Queued %d documents for embedding", len(doc_ids))


@broker.task(schedule=[{"cron": "0 3 * * *"}])  # Daily at 03:00 UTC
async def cleanup_old_documents() -> None:
    """Delete documents older than 90 days, skipping templates, invoices, and parents."""
    cutoff = date.today() - timedelta(days=90)
    keep_types = (DocumentType.template, DocumentType.invoice)

    async with async_session() as session:
        result = await session.execute(select(Family))
        families = result.scalars().all()

    for family in families:
        family_id = str(family.id)
        token = set_family_context(family_id)
        try:
            async with rls_session(family_id) as session:
                # Fetch candidates before deleting so we can clean up storage
                candidate_result = await session.execute(
                    select(Document.id, Document.storage_path).where(
                        and_(
                            Document.family_id == family.id,
                            cast(Document.created_at, DATE) < cutoff,
                            Document.type.not_in(keep_types),
                            Document.parent_document_id.is_(None),
                        )
                    )
                )
                candidates = candidate_result.all()

                if not candidates:
                    continue

                doc_ids = [row[0] for row in candidates]
                storage_paths = [row[1] for row in candidates if row[1]]

                await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
                await session.commit()

            # Best-effort storage cleanup — outside the DB session
            for path in storage_paths:
                await delete_document(path)

            logger.info(
                "Cleaned up %d document(s) for family %s (cutoff %s)",
                len(doc_ids),
                family.id,
                cutoff,
            )
        except Exception as e:
            logger.error("Document cleanup failed for family %s: %s", family.id, e)
        finally:
            reset_family_context(token)


def _advance_next_run(current: date, frequency: str) -> date:
    """Return the next run date based on the given frequency string."""
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "monthly":
        month = current.month + 1
        year = current.year
        if month > 12:
            month = 1
            year += 1
        day = min(current.day, 28)  # Safe for all months
        return date(year, month, day)
    # Unknown frequency — default to monthly to avoid tight loops
    logger.warning("Unknown recurring frequency '%s', defaulting to monthly", frequency)
    month = current.month + 1
    year = current.year
    if month > 12:
        month = 1
        year += 1
    return date(year, month, min(current.day, 28))


async def _generate_recurring_doc(doc: Document, family_id: str, contact_name: str) -> None:
    """Generate the actual recurring document based on the parent template type."""
    from src.core.reports import generate_monthly_report

    template_type = (
        (doc.metadata_extra or {}).get("recurring", {}).get("template_type", str(doc.type))
    )

    if template_type in ("invoice", "DocumentType.invoice"):
        # Generate invoice PDF using the reports module
        today = date.today()
        pdf_bytes, filename = await generate_monthly_report(
            family_id, year=today.year, month=today.month
        )

        # Save as a new versioned document
        new_doc = Document(
            family_id=doc.family_id,
            user_id=doc.user_id,
            type=doc.type,
            storage_path="pending",
            file_name=filename,
            title=f"{doc.title} — {today.isoformat()}",
            mime_type="application/pdf",
            file_size_bytes=len(pdf_bytes),
            version=(doc.version or 1) + 1,
            parent_document_id=doc.id,
            metadata_extra={"generated_from": str(doc.id), "contact_name": contact_name},
        )
        async with rls_session(family_id) as session:
            session.add(new_doc)
            await session.commit()

        logger.info(
            "Generated recurring document for family=%s parent=%s",
            family_id,
            doc.id,
        )
    else:
        logger.info(
            "Recurring document type '%s' — no auto-generation logic, skipping",
            template_type,
        )


@broker.task(schedule=[{"cron": "0 9 * * *"}])  # Daily at 09:00 UTC
async def generate_recurring_documents() -> None:
    """Log and reschedule recurring documents whose next_run date is due."""
    today = date.today()

    async with async_session() as session:
        result = await session.execute(
            select(Document).where(Document.metadata_extra["recurring"].as_string().is_not(None))
        )
        documents = result.scalars().all()

    for doc in documents:
        family_id = str(doc.family_id)
        token = set_family_context(family_id)
        try:
            recurring: dict = (doc.metadata_extra or {}).get("recurring", {})
            if not recurring:
                continue

            next_run_raw: str | None = recurring.get("next_run")
            frequency: str = recurring.get("frequency", "monthly")

            if not next_run_raw:
                continue

            next_run = date.fromisoformat(next_run_raw)
            if next_run > today:
                continue

            template_type = recurring.get("template_type", doc.type)
            contact_name = recurring.get("contact_name", "")

            logger.info(
                "Recurring document due — family=%s doc_id=%s type=%s contact=%s "
                "next_run=%s frequency=%s",
                doc.family_id,
                doc.id,
                template_type,
                contact_name,
                next_run,
                frequency,
            )

            # Generate the recurring document (e.g. invoice PDF)
            try:
                await _generate_recurring_doc(doc, family_id, contact_name)
            except Exception as gen_err:
                logger.error("Failed to generate recurring document %s: %s", doc.id, gen_err)

            new_next_run = _advance_next_run(next_run, frequency)
            updated_recurring = {**recurring, "next_run": new_next_run.isoformat()}

            async with rls_session(family_id) as session:
                db_result = await session.execute(select(Document).where(Document.id == doc.id))
                db_doc = db_result.scalar_one_or_none()
                if db_doc is None:
                    continue

                db_doc.metadata_extra = {
                    **(db_doc.metadata_extra or {}),
                    "recurring": updated_recurring,
                }
                await session.commit()

            logger.info(
                "Rescheduled recurring document %s → next_run=%s",
                doc.id,
                new_next_run,
            )
        except Exception as e:
            logger.error("Recurring document processing failed for doc %s: %s", doc.id, e)
        finally:
            reset_family_context(token)
