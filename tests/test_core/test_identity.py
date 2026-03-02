"""Tests for core identity layer (Phase 2.3)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.identity import (
    _EMPTY_IDENTITY,
    format_identity_block,
    get_core_identity,
    update_core_identity,
)


class TestGetCoreIdentity:
    async def test_returns_identity_dict(self):
        identity = {"name": "Maria", "preferred_currency": "USD"}
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = identity
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == identity

    async def test_returns_empty_when_no_row(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == _EMPTY_IDENTITY

    async def test_returns_empty_on_error(self):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = Exception("DB down")

        with patch("src.core.identity.async_session", return_value=mock_ctx):
            result = await get_core_identity(str(uuid.uuid4()))
        assert result == _EMPTY_IDENTITY


class TestUpdateCoreIdentity:
    async def test_merges_updates(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria", "preferred_currency": "USD"}

        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_session.commit.return_value = None

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_get = AsyncMock(return_value=current)
        with (
            patch("src.core.identity.get_core_identity", mock_get),
            patch("src.core.identity.async_session", return_value=mock_ctx),
        ):
            result = await update_core_identity(uid, {"occupation": "plumber"})
        assert result["name"] == "Maria"
        assert result["occupation"] == "plumber"
        assert result["preferred_currency"] == "USD"

    async def test_removes_none_values(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria", "occupation": "teacher"}

        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        mock_get = AsyncMock(return_value=current)
        with (
            patch("src.core.identity.get_core_identity", mock_get),
            patch("src.core.identity.async_session", return_value=mock_ctx),
        ):
            result = await update_core_identity(uid, {"occupation": None})
        assert "occupation" not in result
        assert result["name"] == "Maria"

    async def test_returns_current_on_error(self):
        uid = str(uuid.uuid4())
        current = {"name": "Maria"}

        with (
            patch(
                "src.core.identity.get_core_identity",
                new_callable=AsyncMock,
                side_effect=[current, current],
            ),
            patch("src.core.identity.async_session", side_effect=Exception("DB down")),
        ):
            result = await update_core_identity(uid, {"name": "Mary"})
        assert result == current


class TestFormatIdentityBlock:
    def test_empty_identity(self):
        assert format_identity_block({}) == ""

    def test_name_only(self):
        result = format_identity_block({"name": "Maria"})
        assert "<core_identity>" in result
        assert "Name: Maria" in result
        assert "</core_identity>" in result

    def test_full_identity(self):
        identity = {
            "name": "David",
            "occupation": "Plumber",
            "family_members": ["wife Sarah", "son Jake"],
            "preferred_currency": "USD",
            "business_type": "construction",
            "communication_preferences": "brief, no emojis",
        }
        result = format_identity_block(identity)
        assert "Name: David" in result
        assert "Occupation: Plumber" in result
        assert "Family: wife Sarah, son Jake" in result
        assert "Currency: USD" in result
        assert "Business: construction" in result
        assert "Communication: brief, no emojis" in result

    def test_family_as_string(self):
        result = format_identity_block({"family_members": "wife and 2 kids"})
        assert "Family: wife and 2 kids" in result

    def test_important_facts_list(self):
        result = format_identity_block({"important_facts": ["allergic to cats", "vegan"]})
        assert "- allergic to cats" in result
        assert "- vegan" in result

    def test_important_facts_string(self):
        result = format_identity_block({"important_facts": "has diabetes"})
        assert "- has diabetes" in result

    def test_empty_values_skipped(self):
        result = format_identity_block({"name": "", "occupation": None})
        assert result == ""

    def test_only_none_values_returns_empty(self):
        result = format_identity_block({"name": None, "occupation": None})
        assert result == ""
