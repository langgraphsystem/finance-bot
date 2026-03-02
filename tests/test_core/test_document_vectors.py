"""Tests for Document Vector Search (Phase 3.5)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.memory.document_vectors import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEFAULT_HYBRID_LIMIT,
    MAX_CHUNKS_PER_DOCUMENT,
    MIN_TEXT_LENGTH,
    RRF_K,
    chunk_text,
    embed_document,
    search_documents_semantic,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_chunk_size(self):
        assert CHUNK_SIZE == 800

    def test_chunk_overlap(self):
        assert CHUNK_OVERLAP == 100

    def test_max_chunks(self):
        assert MAX_CHUNKS_PER_DOCUMENT == 50

    def test_min_text_length(self):
        assert MIN_TEXT_LENGTH == 20

    def test_default_hybrid_limit(self):
        assert DEFAULT_HYBRID_LIMIT == 10

    def test_rrf_k(self):
        assert RRF_K == 60


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------
class TestChunkText:
    def test_empty_string(self):
        assert chunk_text("") == []

    def test_none_input(self):
        assert chunk_text(None) == []

    def test_short_text_below_min(self):
        assert chunk_text("short") == []

    def test_single_chunk(self):
        text = "A" * 100
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_multiple_chunks_with_overlap(self):
        # 2000 chars -> multiple chunks with 800 size and 100 overlap
        text = "A" * 2000
        chunks = chunk_text(text)
        assert len(chunks) >= 2
        # Each chunk should be <= CHUNK_SIZE
        for c in chunks:
            assert len(c) <= CHUNK_SIZE

    def test_chunks_have_step_of_700(self):
        """Chunks advance by CHUNK_SIZE - CHUNK_OVERLAP = 700 chars."""
        text = "".join(str(i % 10) for i in range(2100))
        chunks = chunk_text(text)
        # 2100 / 700 = 3 full steps, so 3 chunks
        assert len(chunks) == 3

    def test_max_chunks_cap(self):
        text = "C" * (CHUNK_SIZE * 100)
        chunks = chunk_text(text)
        assert len(chunks) <= MAX_CHUNKS_PER_DOCUMENT

    def test_whitespace_only_skipped(self):
        text = "   " * 50
        chunks = chunk_text(text)
        assert all(c.strip() for c in chunks)


# ---------------------------------------------------------------------------
# embed_document
# ---------------------------------------------------------------------------
def _mock_db_sessions(doc_obj):
    """Build mock async_session that returns doc_obj on first call, then
    allows delete and insert on subsequent calls."""
    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        mock_session = AsyncMock()
        mock_result = MagicMock()

        if call_count == 1:
            # First session: document lookup
            mock_result.scalar_one_or_none.return_value = doc_obj
            mock_session.execute.return_value = mock_result
        # Subsequent sessions: delete + insert (just accept everything)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False
        return mock_ctx

    return session_factory


class TestEmbedDocument:
    async def test_embeds_document_chunks(self):
        fake_doc = MagicMock()
        fake_doc.extracted_text = "A" * 2000
        fake_doc.family_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        fake_embedding = [0.1] * 1536

        with (
            patch("src.core.db.async_session", side_effect=_mock_db_sessions(fake_doc)),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=fake_embedding,
            ),
        ):
            count = await embed_document("00000000-0000-0000-0000-000000000099")

        assert count >= 2  # 2000 chars → multiple chunks

    async def test_no_text_returns_zero(self):
        fake_doc = MagicMock()
        fake_doc.extracted_text = None

        with patch("src.core.db.async_session", side_effect=_mock_db_sessions(fake_doc)):
            count = await embed_document("00000000-0000-0000-0000-000000000099")

        assert count == 0

    async def test_document_not_found_returns_zero(self):
        with patch("src.core.db.async_session", side_effect=_mock_db_sessions(None)):
            count = await embed_document("00000000-0000-0000-0000-000000000099")

        assert count == 0

    async def test_embedding_failure_skips_chunk(self):
        fake_doc = MagicMock()
        fake_doc.extracted_text = "A" * 500  # one chunk
        fake_doc.family_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch("src.core.db.async_session", side_effect=_mock_db_sessions(fake_doc)),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            count = await embed_document("00000000-0000-0000-0000-000000000099")

        assert count == 0

    async def test_db_failure_returns_zero(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        with patch("src.core.db.async_session", return_value=mock_ctx):
            count = await embed_document("00000000-0000-0000-0000-000000000099")

        assert count == 0


# ---------------------------------------------------------------------------
# search_documents_semantic
# ---------------------------------------------------------------------------
class TestSearchDocumentsSemantic:
    async def test_hybrid_search_combines_results(self):
        fake_embedding = [0.1] * 1536
        doc_id_1 = str(uuid.uuid4())
        doc_id_2 = str(uuid.uuid4())

        semantic_row = (
            uuid.UUID(doc_id_1), "chunk about finance", 0, 0.85,
            "Finance Report", "finance.pdf", None,
        )
        lexical_row = (
            uuid.UUID(doc_id_2), "Tax Summary", "tax.pdf",
            "This is about tax deductions and finance", None,
        )

        mock_session = AsyncMock()
        semantic_result = MagicMock()
        semantic_result.fetchall.return_value = [semantic_row]
        lexical_result = MagicMock()
        lexical_result.fetchall.return_value = [lexical_row]

        mock_session.execute.side_effect = [semantic_result, lexical_result]

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=fake_embedding,
            ),
        ):
            results = await search_documents_semantic("finance", fid, limit=10)

        assert len(results) == 2
        doc_ids = {r["document_id"] for r in results}
        assert doc_id_1 in doc_ids
        assert doc_id_2 in doc_ids

    async def test_semantic_only_when_no_lexical(self):
        fake_embedding = [0.1] * 1536
        doc_id = str(uuid.uuid4())

        semantic_row = (
            uuid.UUID(doc_id), "relevant chunk", 0, 0.9,
            "Report", "report.pdf", None,
        )

        mock_session = AsyncMock()
        semantic_result = MagicMock()
        semantic_result.fetchall.return_value = [semantic_row]
        lexical_result = MagicMock()
        lexical_result.fetchall.return_value = []

        mock_session.execute.side_effect = [semantic_result, lexical_result]

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=fake_embedding,
            ),
        ):
            results = await search_documents_semantic("analysis", fid)

        assert len(results) == 1
        assert results[0]["match_type"] == "semantic"

    async def test_lexical_only_when_embedding_fails(self):
        doc_id = str(uuid.uuid4())

        lexical_row = (
            uuid.UUID(doc_id), "Invoice 2026", "invoice.pdf",
            "Invoice for January 2026 services", None,
        )

        mock_session = AsyncMock()
        lexical_result = MagicMock()
        lexical_result.fetchall.return_value = [lexical_row]
        mock_session.execute.return_value = lexical_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            results = await search_documents_semantic("invoice", fid)

        assert len(results) == 1
        assert results[0]["match_type"] == "lexical"

    async def test_rrf_boosts_docs_in_both(self):
        """Documents found by both methods should rank higher."""
        fake_embedding = [0.1] * 1536
        doc_both = str(uuid.uuid4())
        doc_semantic_only = str(uuid.uuid4())
        doc_lexical_only = str(uuid.uuid4())

        semantic_rows = [
            (uuid.UUID(doc_both), "chunk A", 0, 0.8, "DocA", "a.pdf", None),
            (uuid.UUID(doc_semantic_only), "chunk B", 0, 0.7, "DocB", "b.pdf", None),
        ]
        lexical_rows = [
            (uuid.UUID(doc_lexical_only), "DocC", "c.pdf", "text C", None),
            (uuid.UUID(doc_both), "DocA", "a.pdf", "text A", None),
        ]

        mock_session = AsyncMock()
        sem_result = MagicMock()
        sem_result.fetchall.return_value = semantic_rows
        lex_result = MagicMock()
        lex_result.fetchall.return_value = lexical_rows

        mock_session.execute.side_effect = [sem_result, lex_result]

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=fake_embedding,
            ),
        ):
            results = await search_documents_semantic("query", fid)

        # doc_both should be first (highest RRF score — appears in both)
        assert results[0]["document_id"] == doc_both
        assert results[0]["match_type"] == "semantic+lexical"
        assert len(results) == 3

    async def test_empty_results(self):
        mock_session = AsyncMock()
        sem_result = MagicMock()
        sem_result.fetchall.return_value = []
        lex_result = MagicMock()
        lex_result.fetchall.return_value = []

        mock_session.execute.side_effect = [sem_result, lex_result]

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=[0.1] * 1536,
            ),
        ):
            results = await search_documents_semantic("nonexistent", fid)

        assert results == []

    async def test_db_failure_returns_empty(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        fid = "00000000-0000-0000-0000-000000000001"

        with (
            patch("src.core.db.async_session", return_value=mock_ctx),
            patch(
                "src.core.memory.document_vectors._get_embedding",
                new_callable=AsyncMock,
                return_value=[0.1] * 1536,
            ),
        ):
            results = await search_documents_semantic("test", fid)

        assert results == []


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------
class TestBackgroundTask:
    async def test_async_embed_document_calls_embed(self):
        from src.core.tasks.document_tasks import async_embed_document

        with patch(
            "src.core.memory.document_vectors.embed_document",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_embed:
            result = await async_embed_document.original_func(
                "00000000-0000-0000-0000-000000000099"
            )

        assert result == 5
        mock_embed.assert_called_once_with("00000000-0000-0000-0000-000000000099")


# ---------------------------------------------------------------------------
# Search Documents Skill (handler)
# ---------------------------------------------------------------------------
class TestSearchDocumentsSkill:
    async def test_uses_hybrid_when_available(self):
        from src.skills.search_documents.handler import SearchDocumentsSkill

        skill = SearchDocumentsSkill()
        msg = MagicMock()
        msg.text = "finance report"
        ctx = MagicMock()
        ctx.family_id = "00000000-0000-0000-0000-000000000001"
        ctx.language = "en"

        hybrid_results = [
            {
                "document_id": "abc",
                "title": "Finance Q1",
                "file_name": "q1.pdf",
                "chunk_text": "Revenue was 100K",
                "score": 0.5,
                "match_type": "semantic+lexical",
            }
        ]

        with patch.object(
            skill, "_hybrid_search", new_callable=AsyncMock, return_value=hybrid_results
        ):
            result = await skill.execute(msg, ctx, {"search_query": "finance report"})

        assert "Finance Q1" in result.response_text
        assert "\U0001f50d" in result.response_text  # semantic match icon

    async def test_falls_back_to_ilike(self):
        from src.skills.search_documents.handler import SearchDocumentsSkill

        skill = SearchDocumentsSkill()
        msg = MagicMock()
        msg.text = "invoice"
        ctx = MagicMock()
        ctx.family_id = "00000000-0000-0000-0000-000000000001"
        ctx.language = "en"

        with (
            patch.object(
                skill, "_hybrid_search", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(
                skill, "_ilike_search", new_callable=AsyncMock,
                return_value=MagicMock(response_text="Found via ILIKE"),
            ) as mock_ilike,
        ):
            result = await skill.execute(msg, ctx, {"search_query": "invoice"})

        mock_ilike.assert_called_once()
        assert result.response_text == "Found via ILIKE"

    async def test_empty_query(self):
        from src.skills.search_documents.handler import SearchDocumentsSkill

        skill = SearchDocumentsSkill()
        msg = MagicMock()
        msg.text = ""
        ctx = MagicMock()
        ctx.language = "en"

        result = await skill.execute(msg, ctx, {})

        assert "search for" in result.response_text.lower()
