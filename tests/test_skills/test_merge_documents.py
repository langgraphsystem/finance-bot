"""Tests for merge_documents skill."""

from unittest.mock import AsyncMock, patch

from src.skills.merge_documents.handler import skill


async def test_merge_no_file_no_context(sample_context, text_message):
    """No document and no pending merge — shows instruction message."""
    with patch("src.skills.merge_documents.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await skill.execute(text_message, sample_context, {})
    assert "pdf" in result.response_text.lower()
    assert "send" in result.response_text.lower() or "merge" in result.response_text.lower()


async def test_merge_attributes():
    assert skill.name == "merge_documents"
    assert "merge_documents" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
