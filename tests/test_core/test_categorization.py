"""Tests for hybrid RAG categorization pipeline."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.categorization import (
    CategoryPrediction,
    categorize_transaction,
    _match_by_rules,
    _match_by_similarity,
    _classify_with_llm,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAMILY_ID = str(uuid.uuid4())
CAT_ID_FOOD = str(uuid.uuid4())
CAT_ID_FUEL = str(uuid.uuid4())

CATEGORIES = [
    {"id": CAT_ID_FOOD, "name": "Продукты"},
    {"id": CAT_ID_FUEL, "name": "Дизель"},
]


# ---------------------------------------------------------------------------
# CategoryPrediction unit tests
# ---------------------------------------------------------------------------

def test_category_prediction_fields():
    """CategoryPrediction has all expected fields."""
    pred = CategoryPrediction(
        category_id="abc-123",
        category_name="Продукты",
        confidence=0.9,
        method="rule",
    )
    assert pred.category_id == "abc-123"
    assert pred.category_name == "Продукты"
    assert pred.confidence == 0.9
    assert pred.method == "rule"


def test_category_prediction_repr():
    """CategoryPrediction repr is readable."""
    pred = CategoryPrediction(
        category_id="x", category_name="Дизель", confidence=0.85, method="rag",
    )
    r = repr(pred)
    assert "Дизель" in r
    assert "0.85" in r
    assert "rag" in r


# ---------------------------------------------------------------------------
# Step 1: Rule-based matching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_by_rules_found():
    """Rule-based match returns correct category when mapping exists."""
    mock_mapping = MagicMock()
    mock_mapping.category_id = uuid.UUID(CAT_ID_FUEL)
    mock_mapping.usage_count = 50

    mock_result = MagicMock()
    mock_result.first.return_value = (mock_mapping, "Дизель")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.categorization.async_session", return_value=mock_session):
        result = await _match_by_rules("Shell", FAMILY_ID)

    assert result is not None
    assert result.category_id == CAT_ID_FUEL
    assert result.category_name == "Дизель"
    assert result.method == "rule"
    assert 0.5 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_match_by_rules_not_found():
    """Rule-based match returns None when no mapping found."""
    mock_result = MagicMock()
    mock_result.first.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.categorization.async_session", return_value=mock_session):
        result = await _match_by_rules("UnknownMerchant", FAMILY_ID)

    assert result is None


# ---------------------------------------------------------------------------
# Step 2: Vector similarity search (graceful degradation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_by_similarity_pgvector_not_available():
    """Vector search returns None gracefully when pgvector is unavailable."""
    mock_openai = MagicMock()
    mock_embeddings = AsyncMock()
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1] * 1536
    mock_embeddings_response = MagicMock()
    mock_embeddings_response.data = [mock_embedding_data]
    mock_openai.embeddings.create = AsyncMock(return_value=mock_embeddings_response)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("pgvector not available"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.categorization.openai_client", return_value=mock_openai),
        patch("src.core.categorization.async_session", return_value=mock_session),
    ):
        result = await _match_by_similarity("заправка Shell", FAMILY_ID, CATEGORIES)

    assert result is None


@pytest.mark.asyncio
async def test_match_by_similarity_no_results():
    """Vector search returns None when no similar transactions found."""
    mock_openai = MagicMock()
    mock_embedding_data = MagicMock()
    mock_embedding_data.embedding = [0.1] * 1536
    mock_embeddings_response = MagicMock()
    mock_embeddings_response.data = [mock_embedding_data]
    mock_openai.embeddings.create = AsyncMock(return_value=mock_embeddings_response)

    mock_result = MagicMock()
    mock_result.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.categorization.openai_client", return_value=mock_openai),
        patch("src.core.categorization.async_session", return_value=mock_session),
    ):
        result = await _match_by_similarity("заправка Shell", FAMILY_ID, CATEGORIES)

    assert result is None


@pytest.mark.asyncio
async def test_match_by_similarity_openai_fails():
    """Vector search returns None when OpenAI embedding call fails."""
    mock_openai = MagicMock()
    mock_openai.embeddings.create = AsyncMock(side_effect=Exception("API error"))

    with patch("src.core.categorization.openai_client", return_value=mock_openai):
        result = await _match_by_similarity("заправка Shell", FAMILY_ID, CATEGORIES)

    assert result is None


# ---------------------------------------------------------------------------
# Step 3: LLM classification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_with_llm_success():
    """LLM classification returns a valid prediction."""
    from pydantic import BaseModel, Field

    mock_llm_result = MagicMock()
    mock_llm_result.category_name = "Продукты"
    mock_llm_result.confidence = 0.88

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_llm_result)
    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("src.core.categorization.get_instructor_anthropic", return_value=mock_client):
        result = await _classify_with_llm(
            description="Walmart groceries",
            merchant="Walmart",
            available_categories=CATEGORIES,
        )

    assert result is not None
    assert result.category_id == CAT_ID_FOOD
    assert result.category_name == "Продукты"
    assert result.confidence == 0.88
    assert result.method == "llm"


@pytest.mark.asyncio
async def test_classify_with_llm_unknown_category_fallback():
    """LLM returns unknown category name -> falls back to first available."""
    mock_llm_result = MagicMock()
    mock_llm_result.category_name = "НеизвестнаяКатегория"
    mock_llm_result.confidence = 0.7

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_llm_result)
    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("src.core.categorization.get_instructor_anthropic", return_value=mock_client):
        result = await _classify_with_llm(
            description="something unknown",
            merchant=None,
            available_categories=CATEGORIES,
        )

    assert result is not None
    # Falls back to first category
    assert result.category_id == CAT_ID_FOOD
    assert result.category_name == "Продукты"
    assert result.method == "llm"


@pytest.mark.asyncio
async def test_classify_with_llm_failure():
    """LLM classification returns None on error."""
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("LLM error"))

    with patch("src.core.categorization.get_instructor_anthropic", return_value=mock_client):
        result = await _classify_with_llm(
            description="mystery purchase",
            merchant=None,
            available_categories=CATEGORIES,
        )

    assert result is None


@pytest.mark.asyncio
async def test_classify_with_llm_with_rag_context():
    """LLM classification includes RAG context in prompt when provided."""
    rag_ctx = CategoryPrediction(
        category_id=CAT_ID_FUEL, category_name="Дизель", confidence=0.65, method="rag",
    )

    mock_llm_result = MagicMock()
    mock_llm_result.category_name = "Дизель"
    mock_llm_result.confidence = 0.82

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_llm_result)
    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("src.core.categorization.get_instructor_anthropic", return_value=mock_client):
        result = await _classify_with_llm(
            description="Shell fuel stop",
            merchant="Shell",
            available_categories=CATEGORIES,
            rag_context=rag_ctx,
        )

    assert result is not None
    assert result.category_name == "Дизель"
    assert result.method == "llm"

    # Verify prompt included context about similar transactions
    call_kwargs = mock_messages.create.call_args.kwargs
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Дизель" in prompt_text


# ---------------------------------------------------------------------------
# Full pipeline integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_rule_match_short_circuits():
    """When rule-based match succeeds, RAG and LLM are not called."""
    rule_pred = CategoryPrediction(
        category_id=CAT_ID_FUEL, category_name="Дизель", confidence=0.85, method="rule",
    )

    with (
        patch("src.core.categorization._match_by_rules", new_callable=AsyncMock, return_value=rule_pred) as mock_rules,
        patch("src.core.categorization._match_by_similarity", new_callable=AsyncMock) as mock_rag,
        patch("src.core.categorization._classify_with_llm", new_callable=AsyncMock) as mock_llm,
    ):
        result = await categorize_transaction(
            description="Shell diesel",
            merchant="Shell",
            family_id=FAMILY_ID,
            available_categories=CATEGORIES,
        )

    assert result is not None
    assert result.method == "rule"
    mock_rules.assert_awaited_once()
    mock_rag.assert_not_awaited()
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_no_rule_falls_through_to_rag():
    """When rules fail and RAG has high confidence, RAG result is returned."""
    rag_pred = CategoryPrediction(
        category_id=CAT_ID_FOOD, category_name="Продукты", confidence=0.8, method="rag",
    )

    with (
        patch("src.core.categorization._match_by_rules", new_callable=AsyncMock, return_value=None),
        patch("src.core.categorization._match_by_similarity", new_callable=AsyncMock, return_value=rag_pred) as mock_rag,
        patch("src.core.categorization._classify_with_llm", new_callable=AsyncMock) as mock_llm,
    ):
        result = await categorize_transaction(
            description="Walmart groceries",
            merchant="Walmart",
            family_id=FAMILY_ID,
            available_categories=CATEGORIES,
        )

    assert result is not None
    assert result.method == "rag"
    assert result.confidence >= 0.7
    mock_rag.assert_awaited_once()
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_low_rag_confidence_falls_through_to_llm():
    """When RAG confidence is below threshold, LLM is called with RAG context."""
    rag_pred = CategoryPrediction(
        category_id=CAT_ID_FOOD, category_name="Продукты", confidence=0.5, method="rag",
    )
    llm_pred = CategoryPrediction(
        category_id=CAT_ID_FOOD, category_name="Продукты", confidence=0.82, method="llm",
    )

    with (
        patch("src.core.categorization._match_by_rules", new_callable=AsyncMock, return_value=None),
        patch("src.core.categorization._match_by_similarity", new_callable=AsyncMock, return_value=rag_pred),
        patch("src.core.categorization._classify_with_llm", new_callable=AsyncMock, return_value=llm_pred) as mock_llm,
    ):
        result = await categorize_transaction(
            description="grocery store purchase",
            merchant=None,
            family_id=FAMILY_ID,
            available_categories=CATEGORIES,
        )

    assert result is not None
    assert result.method == "llm"
    # Verify rag_context was passed to LLM
    call_kwargs = mock_llm.call_args.kwargs
    assert call_kwargs["rag_context"] is rag_pred


@pytest.mark.asyncio
async def test_pipeline_no_merchant_skips_rules():
    """When merchant is None, rule-based matching is skipped entirely."""
    llm_pred = CategoryPrediction(
        category_id=CAT_ID_FOOD, category_name="Продукты", confidence=0.75, method="llm",
    )

    with (
        patch("src.core.categorization._match_by_rules", new_callable=AsyncMock) as mock_rules,
        patch("src.core.categorization._match_by_similarity", new_callable=AsyncMock, return_value=None),
        patch("src.core.categorization._classify_with_llm", new_callable=AsyncMock, return_value=llm_pred),
    ):
        result = await categorize_transaction(
            description="bought food",
            merchant=None,
            family_id=FAMILY_ID,
            available_categories=CATEGORIES,
        )

    assert result is not None
    mock_rules.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_all_steps_fail_returns_none():
    """When all steps fail, pipeline returns None."""
    with (
        patch("src.core.categorization._match_by_rules", new_callable=AsyncMock, return_value=None),
        patch("src.core.categorization._match_by_similarity", new_callable=AsyncMock, return_value=None),
        patch("src.core.categorization._classify_with_llm", new_callable=AsyncMock, return_value=None),
    ):
        result = await categorize_transaction(
            description="???",
            merchant="???",
            family_id=FAMILY_ID,
            available_categories=CATEGORIES,
        )

    assert result is None
