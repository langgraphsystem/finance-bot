"""Document vector search — semantic search via pgvector + pg_trgm hybrid.

Chunks documents, embeds via text-embedding-3-small (1536d), stores in
document_embeddings table. Hybrid search combines trigram (lexical) with
cosine similarity (semantic) using Reciprocal Rank Fusion (RRF).

Uses raw SQL for all vector operations (consistent with categories and
few_shot_examples patterns — no pgvector Python dependency required).
"""

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select, text

from src.core.observability import observe

logger = logging.getLogger(__name__)

# Chunking parameters
CHUNK_SIZE = 800  # characters per chunk
CHUNK_OVERLAP = 100  # overlap between chunks
MAX_CHUNKS_PER_DOCUMENT = 50  # cap to avoid excessive embedding cost
MIN_TEXT_LENGTH = 20  # skip documents with very little text

# Search parameters
DEFAULT_SEMANTIC_LIMIT = 20
DEFAULT_HYBRID_LIMIT = 10
RRF_K = 60  # RRF constant (standard value)


def chunk_text(text_content: str) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    if not text_content or len(text_content) < MIN_TEXT_LENGTH:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text_content) and len(chunks) < MAX_CHUNKS_PER_DOCUMENT:
        end = start + CHUNK_SIZE
        chunk = text_content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        # Advance by (CHUNK_SIZE - CHUNK_OVERLAP) to create overlap
        start += CHUNK_SIZE - CHUNK_OVERLAP
        if start >= len(text_content):
            break

    return chunks


async def _get_embedding(text_content: str) -> list[float] | None:
    """Generate embedding using text-embedding-3-small."""
    try:
        from src.core.llm.clients import openai_client

        client = openai_client()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text_content[:8000],  # API limit per input
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


@observe(name="embed_document")
async def embed_document(document_id: str) -> int:
    """Chunk and embed a document. Returns number of chunks stored.

    Deletes existing embeddings for the document before re-embedding.
    """
    from src.core.db import async_session
    from src.core.models.document import Document
    from src.core.models.document_embedding import DocumentEmbedding

    try:
        doc_uuid = uuid.UUID(document_id)

        async with async_session() as session:
            result = await session.execute(
                select(Document).where(Document.id == doc_uuid)
            )
            doc = result.scalar_one_or_none()
            if not doc or not doc.extracted_text:
                return 0

            family_id = doc.family_id
            extracted = doc.extracted_text

        chunks = chunk_text(extracted)
        if not chunks:
            return 0

        # Delete existing embeddings for this document
        async with async_session() as session:
            await session.execute(
                delete(DocumentEmbedding).where(
                    DocumentEmbedding.document_id == doc_uuid
                )
            )
            await session.commit()

        # Embed each chunk and store via raw SQL (vector column)
        stored = 0
        async with async_session() as session:
            for idx, chunk in enumerate(chunks):
                embedding = await _get_embedding(chunk)
                if not embedding:
                    continue

                await session.execute(
                    text("""
                        INSERT INTO document_embeddings
                            (document_id, family_id, chunk_index, chunk_text, embedding)
                        VALUES
                            (:doc_id, :fid, :idx, :chunk, :emb::vector)
                    """),
                    {
                        "doc_id": str(doc_uuid),
                        "fid": str(family_id),
                        "idx": idx,
                        "chunk": chunk,
                        "emb": str(embedding),
                    },
                )
                stored += 1

            await session.commit()

        logger.info(
            "Embedded document %s: %d chunks (from %d chars)",
            document_id, stored, len(extracted),
        )
        return stored
    except Exception as e:
        logger.error("embed_document failed for %s: %s", document_id, e)
        return 0


@observe(name="search_documents_semantic")
async def search_documents_semantic(
    query: str,
    family_id: str,
    limit: int = DEFAULT_HYBRID_LIMIT,
) -> list[dict[str, Any]]:
    """Hybrid search: pg_trgm (lexical) + pgvector (semantic) with RRF.

    Returns list of dicts with: document_id, title, file_name, chunk_text,
    score, match_type.
    """
    from src.core.db import async_session

    fid = uuid.UUID(family_id)

    # Get query embedding
    query_embedding = await _get_embedding(query)

    results: list[dict[str, Any]] = []

    try:
        async with async_session() as session:
            # --- Semantic search (pgvector cosine similarity) ---
            semantic_rows: list[Any] = []
            if query_embedding:
                semantic_result = await session.execute(
                    text("""
                        SELECT
                            de.document_id,
                            de.chunk_text,
                            de.chunk_index,
                            1 - (de.embedding <=> :embedding::vector) AS similarity,
                            d.title,
                            d.file_name,
                            d.created_at
                        FROM document_embeddings de
                        JOIN documents d ON d.id = de.document_id
                        WHERE de.family_id = :family_id
                          AND de.embedding IS NOT NULL
                        ORDER BY de.embedding <=> :embedding::vector
                        LIMIT :limit
                    """),
                    {
                        "embedding": str(query_embedding),
                        "family_id": str(fid),
                        "limit": DEFAULT_SEMANTIC_LIMIT,
                    },
                )
                semantic_rows = list(semantic_result.fetchall())

            # --- Lexical search (pg_trgm via ILIKE on documents table) ---
            search_pattern = f"%{query}%"
            lexical_result = await session.execute(
                text("""
                    SELECT
                        d.id AS document_id,
                        d.title,
                        d.file_name,
                        d.extracted_text,
                        d.created_at
                    FROM documents d
                    WHERE d.family_id = :family_id
                      AND (
                          d.extracted_text ILIKE :pattern
                          OR d.title ILIKE :pattern
                          OR d.file_name ILIKE :pattern
                      )
                    ORDER BY d.created_at DESC
                    LIMIT :limit
                """),
                {
                    "family_id": str(fid),
                    "pattern": search_pattern,
                    "limit": DEFAULT_SEMANTIC_LIMIT,
                },
            )
            lexical_rows = list(lexical_result.fetchall())

        # --- Reciprocal Rank Fusion ---
        # Build rank maps: document_id -> rank position
        semantic_ranks: dict[str, int] = {}
        semantic_chunks: dict[str, tuple[str, float]] = {}  # doc_id -> (chunk, sim)
        for rank, row in enumerate(semantic_rows):
            doc_id = str(row[0])
            if doc_id not in semantic_ranks:
                semantic_ranks[doc_id] = rank
                semantic_chunks[doc_id] = (row[1], float(row[3]))

        lexical_ranks: dict[str, int] = {}
        lexical_data: dict[str, tuple[str, str, str]] = {}  # doc_id -> (title, fname, text)
        for rank, row in enumerate(lexical_rows):
            doc_id = str(row[0])
            if doc_id not in lexical_ranks:
                lexical_ranks[doc_id] = rank
                lexical_data[doc_id] = (row[1], row[2], row[3])

        # Combine all document IDs
        all_doc_ids = set(semantic_ranks.keys()) | set(lexical_ranks.keys())

        # Compute RRF scores
        scored: list[tuple[str, float, str]] = []
        for doc_id in all_doc_ids:
            rrf_score = 0.0
            match_type_parts: list[str] = []

            if doc_id in semantic_ranks:
                rrf_score += 1.0 / (RRF_K + semantic_ranks[doc_id])
                match_type_parts.append("semantic")

            if doc_id in lexical_ranks:
                rrf_score += 1.0 / (RRF_K + lexical_ranks[doc_id])
                match_type_parts.append("lexical")

            scored.append((doc_id, rrf_score, "+".join(match_type_parts)))

        # Sort by RRF score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Build result dicts
        for doc_id, rrf_score, match_type in scored[:limit]:
            # Get best snippet
            chunk_text_val = ""
            if doc_id in semantic_chunks:
                chunk_text_val = semantic_chunks[doc_id][0]
            elif doc_id in lexical_data:
                full_text = lexical_data[doc_id][2] or ""
                # Extract snippet around query match
                lower_text = full_text.lower()
                idx = lower_text.find(query.lower())
                if idx >= 0:
                    start = max(0, idx - 50)
                    end = min(len(full_text), idx + len(query) + 50)
                    chunk_text_val = full_text[start:end]
                else:
                    chunk_text_val = full_text[:200]

            # Get title/filename
            title = ""
            file_name = ""
            if doc_id in semantic_chunks:
                # Fetch from semantic result metadata
                for row in semantic_rows:
                    if str(row[0]) == doc_id:
                        title = row[4] or ""
                        file_name = row[5] or ""
                        break
            if not title and doc_id in lexical_data:
                title = lexical_data[doc_id][0] or ""
                file_name = lexical_data[doc_id][1] or ""

            results.append({
                "document_id": doc_id,
                "title": title,
                "file_name": file_name,
                "chunk_text": chunk_text_val,
                "score": rrf_score,
                "match_type": match_type,
            })

    except Exception as e:
        logger.error("Hybrid search failed: %s", e)

    return results
