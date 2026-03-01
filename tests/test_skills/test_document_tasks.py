"""Tests for document cron tasks — cleanup and recurring generation."""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.tasks.document_tasks import _advance_next_run

# --- _advance_next_run pure function tests ---


async def test_advance_next_run_daily():
    result = _advance_next_run(date(2026, 3, 1), "daily")
    assert result == date(2026, 3, 2)


async def test_advance_next_run_daily_end_of_month():
    result = _advance_next_run(date(2026, 3, 31), "daily")
    assert result == date(2026, 4, 1)


async def test_advance_next_run_daily_leap_year():
    result = _advance_next_run(date(2028, 2, 28), "daily")
    assert result == date(2028, 2, 29)


async def test_advance_next_run_weekly():
    result = _advance_next_run(date(2026, 3, 1), "weekly")
    assert result == date(2026, 3, 8)


async def test_advance_next_run_weekly_across_month():
    result = _advance_next_run(date(2026, 3, 28), "weekly")
    assert result == date(2026, 4, 4)


async def test_advance_next_run_monthly():
    result = _advance_next_run(date(2026, 3, 15), "monthly")
    assert result == date(2026, 4, 15)


async def test_advance_next_run_monthly_day_capped():
    """Month with 31 days → next month with 30 days — day capped to 28."""
    result = _advance_next_run(date(2026, 1, 31), "monthly")
    assert result == date(2026, 2, 28)


async def test_advance_next_run_december_to_january():
    """December → January of next year."""
    result = _advance_next_run(date(2026, 12, 31), "monthly")
    assert result == date(2027, 1, 28)


async def test_advance_next_run_december_15():
    """December 15 → January 15 of next year (day <= 28, no capping)."""
    result = _advance_next_run(date(2026, 12, 15), "monthly")
    assert result == date(2027, 1, 15)


async def test_advance_next_run_unknown_frequency():
    """Unknown frequency — defaults to monthly."""
    result = _advance_next_run(date(2026, 6, 10), "biweekly")
    assert result == date(2026, 7, 10)


async def test_advance_next_run_unknown_frequency_december():
    """Unknown frequency in December — wraps to next year."""
    result = _advance_next_run(date(2026, 12, 20), "quarterly")
    assert result == date(2027, 1, 20)


# --- cleanup_old_documents task tests ---


async def test_cleanup_old_documents_no_families():
    """No families in DB — task completes without error."""
    from src.core.tasks.document_tasks import cleanup_old_documents

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.core.tasks.document_tasks.async_session", return_value=mock_session):
        await cleanup_old_documents()


async def test_cleanup_old_documents_with_candidates():
    """Family has old documents — deletes them from DB and storage."""
    from src.core.tasks.document_tasks import cleanup_old_documents

    family_id = uuid.uuid4()
    mock_family = MagicMock()
    mock_family.id = family_id

    # First async_session call: list families
    families_result = MagicMock()
    families_result.scalars.return_value.all.return_value = [mock_family]

    family_session = AsyncMock()
    family_session.execute = AsyncMock(return_value=families_result)
    family_session.__aenter__ = AsyncMock(return_value=family_session)
    family_session.__aexit__ = AsyncMock(return_value=None)

    # RLS session call: fetch candidates + delete
    doc_id = uuid.uuid4()
    candidates_result = MagicMock()
    candidates_result.all.return_value = [
        (doc_id, "documents/old_file.pdf"),
    ]

    delete_result = MagicMock()

    rls_sess = AsyncMock()
    rls_sess.execute = AsyncMock(side_effect=[candidates_result, delete_result])
    rls_sess.commit = AsyncMock()
    rls_sess.__aenter__ = AsyncMock(return_value=rls_sess)
    rls_sess.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.core.tasks.document_tasks.async_session", return_value=family_session),
        patch("src.core.tasks.document_tasks.rls_session", return_value=rls_sess),
        patch("src.core.tasks.document_tasks.set_family_context", return_value="token"),
        patch("src.core.tasks.document_tasks.reset_family_context"),
        patch(
            "src.core.tasks.document_tasks.delete_document",
            new_callable=AsyncMock,
        ) as mock_delete_storage,
    ):
        await cleanup_old_documents()

    rls_sess.commit.assert_called_once()
    mock_delete_storage.assert_called_once_with("documents/old_file.pdf")


async def test_cleanup_old_documents_no_candidates():
    """Family exists but no old documents — nothing deleted."""
    from src.core.tasks.document_tasks import cleanup_old_documents

    mock_family = MagicMock()
    mock_family.id = uuid.uuid4()

    families_result = MagicMock()
    families_result.scalars.return_value.all.return_value = [mock_family]

    family_session = AsyncMock()
    family_session.execute = AsyncMock(return_value=families_result)
    family_session.__aenter__ = AsyncMock(return_value=family_session)
    family_session.__aexit__ = AsyncMock(return_value=None)

    # RLS session: no candidates
    empty_result = MagicMock()
    empty_result.all.return_value = []

    rls_sess = AsyncMock()
    rls_sess.execute = AsyncMock(return_value=empty_result)
    rls_sess.__aenter__ = AsyncMock(return_value=rls_sess)
    rls_sess.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.core.tasks.document_tasks.async_session", return_value=family_session),
        patch("src.core.tasks.document_tasks.rls_session", return_value=rls_sess),
        patch("src.core.tasks.document_tasks.set_family_context", return_value="token"),
        patch("src.core.tasks.document_tasks.reset_family_context"),
        patch(
            "src.core.tasks.document_tasks.delete_document",
            new_callable=AsyncMock,
        ) as mock_delete_storage,
    ):
        await cleanup_old_documents()

    # commit should NOT have been called (early continue)
    rls_sess.commit.assert_not_called()
    mock_delete_storage.assert_not_called()


# --- generate_recurring_documents task tests ---


async def test_generate_recurring_no_documents():
    """No documents with recurring metadata — task completes cleanly."""
    from src.core.tasks.document_tasks import generate_recurring_documents

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.core.tasks.document_tasks.async_session", return_value=mock_session):
        await generate_recurring_documents()


async def test_generate_recurring_future_next_run():
    """Document has next_run in the future — skipped."""
    from src.core.tasks.document_tasks import generate_recurring_documents

    future_date = (date.today() + timedelta(days=7)).isoformat()
    mock_doc = MagicMock()
    mock_doc.family_id = uuid.uuid4()
    mock_doc.id = uuid.uuid4()
    mock_doc.metadata_extra = {
        "recurring": {
            "next_run": future_date,
            "frequency": "weekly",
        }
    }

    docs_result = MagicMock()
    docs_result.scalars.return_value.all.return_value = [mock_doc]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=docs_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.core.tasks.document_tasks.async_session", return_value=mock_session),
        patch("src.core.tasks.document_tasks.set_family_context", return_value="token"),
        patch("src.core.tasks.document_tasks.reset_family_context"),
        patch(
            "src.core.tasks.document_tasks._generate_recurring_doc",
            new_callable=AsyncMock,
        ) as mock_gen,
    ):
        await generate_recurring_documents()

    # Should NOT have generated (future date)
    mock_gen.assert_not_called()


async def test_generate_recurring_due_document():
    """Document has next_run in the past — generates and reschedules."""
    from src.core.tasks.document_tasks import generate_recurring_documents

    family_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    past_date = (date.today() - timedelta(days=1)).isoformat()

    mock_doc = MagicMock()
    mock_doc.family_id = family_id
    mock_doc.id = doc_id
    mock_doc.type = "invoice"
    mock_doc.metadata_extra = {
        "recurring": {
            "next_run": past_date,
            "frequency": "monthly",
            "template_type": "invoice",
            "contact_name": "ACME Corp",
        }
    }

    docs_result = MagicMock()
    docs_result.scalars.return_value.all.return_value = [mock_doc]

    initial_session = AsyncMock()
    initial_session.execute = AsyncMock(return_value=docs_result)
    initial_session.__aenter__ = AsyncMock(return_value=initial_session)
    initial_session.__aexit__ = AsyncMock(return_value=None)

    # RLS session for rescheduling
    db_doc_result = MagicMock()
    db_doc_mock = MagicMock()
    db_doc_mock.metadata_extra = dict(mock_doc.metadata_extra)
    db_doc_result.scalar_one_or_none.return_value = db_doc_mock

    rls_sess = AsyncMock()
    rls_sess.execute = AsyncMock(return_value=db_doc_result)
    rls_sess.commit = AsyncMock()
    rls_sess.__aenter__ = AsyncMock(return_value=rls_sess)
    rls_sess.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.core.tasks.document_tasks.async_session", return_value=initial_session),
        patch("src.core.tasks.document_tasks.rls_session", return_value=rls_sess),
        patch("src.core.tasks.document_tasks.set_family_context", return_value="token"),
        patch("src.core.tasks.document_tasks.reset_family_context"),
        patch(
            "src.core.tasks.document_tasks._generate_recurring_doc",
            new_callable=AsyncMock,
        ) as mock_gen,
    ):
        await generate_recurring_documents()

    mock_gen.assert_called_once_with(mock_doc, str(family_id), "ACME Corp")
    rls_sess.commit.assert_called_once()
    # Verify next_run was updated on the db_doc
    new_meta = db_doc_mock.metadata_extra
    assert "recurring" in new_meta
    assert new_meta["recurring"]["next_run"] is not None


async def test_generate_recurring_no_next_run():
    """Document has recurring but no next_run — skipped."""
    from src.core.tasks.document_tasks import generate_recurring_documents

    mock_doc = MagicMock()
    mock_doc.family_id = uuid.uuid4()
    mock_doc.id = uuid.uuid4()
    mock_doc.metadata_extra = {
        "recurring": {
            "frequency": "daily",
            # next_run intentionally missing
        }
    }

    docs_result = MagicMock()
    docs_result.scalars.return_value.all.return_value = [mock_doc]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=docs_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.core.tasks.document_tasks.async_session", return_value=mock_session),
        patch("src.core.tasks.document_tasks.set_family_context", return_value="token"),
        patch("src.core.tasks.document_tasks.reset_family_context"),
        patch(
            "src.core.tasks.document_tasks._generate_recurring_doc",
            new_callable=AsyncMock,
        ) as mock_gen,
    ):
        await generate_recurring_documents()

    mock_gen.assert_not_called()
