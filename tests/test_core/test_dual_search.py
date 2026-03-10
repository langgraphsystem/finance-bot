"""Tests for dual-search executor (Gemini + Grok parallel search)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.research.dual_search import dual_search


@pytest.fixture()
def gemini_searcher():
    return AsyncMock(return_value="Gemini result about restaurants in Almaty")


class TestDualSearchBothProviders:
    async def test_both_succeed_calls_synthesis(self, gemini_searcher):
        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                return_value="Grok result about restaurants",
            ),
            patch(
                "src.core.research.dual_search._gemini_synthesize",
                new_callable=AsyncMock,
                return_value="Synthesized result",
            ) as mock_synth,
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "restaurants in Almaty", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Synthesized result"
            mock_synth.assert_called_once()

    async def test_synthesis_fails_returns_gemini(self, gemini_searcher):
        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                return_value="Grok result",
            ),
            patch(
                "src.core.research.dual_search._gemini_synthesize",
                new_callable=AsyncMock,
                side_effect=Exception("synthesis error"),
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Gemini result about restaurants in Almaty"


class TestDualSearchPartialFailure:
    async def test_only_gemini_succeeds(self, gemini_searcher):
        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                side_effect=Exception("grok error"),
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Gemini result about restaurants in Almaty"

    async def test_only_grok_succeeds(self):
        failing_gemini = AsyncMock(side_effect=Exception("gemini error"))

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                return_value="Grok result",
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=failing_gemini,
            )

            assert result == "Grok result"

    async def test_both_fail_returns_error(self):
        failing_gemini = AsyncMock(side_effect=Exception("gemini error"))

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                side_effect=Exception("grok error"),
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=failing_gemini,
            )

            assert "search results" in result.lower()

    async def test_both_fail_russian_error(self):
        failing_gemini = AsyncMock(side_effect=Exception("error"))

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                side_effect=Exception("error"),
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "ru", "",
                gemini_searcher=failing_gemini,
            )

            assert "результаты поиска" in result.lower()

    @pytest.mark.parametrize(
        ("lang", "expected_fragment"),
        [
            ("de", "suchergebnisse"),
            ("fr", "résultats"),
            ("tr", "arama"),
            ("uk", "результати"),
            ("kk", "іздеу"),
            ("ja", "検索結果"),
            ("ko", "검색"),
            ("zh", "搜索结果"),
            ("th", "ผลการค้นหา"),
            ("xx", "search results"),  # unknown lang → English fallback
        ],
    )
    async def test_both_fail_multilingual_error(self, lang, expected_fragment):
        failing_gemini = AsyncMock(side_effect=Exception("error"))

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                side_effect=Exception("error"),
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", lang, "",
                gemini_searcher=failing_gemini,
            )

            assert expected_fragment in result.lower()


class TestDualSearchGuards:
    async def test_feature_flag_off_uses_gemini_only(self, gemini_searcher):
        with patch("src.core.research.dual_search.settings") as mock_settings:
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = False

            result = await dual_search(
                "restaurants in Almaty", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Gemini result about restaurants in Almaty"
            gemini_searcher.assert_called_once_with("restaurants in Almaty", "en", "")

    async def test_no_xai_key_uses_gemini_only(self, gemini_searcher):
        with patch("src.core.research.dual_search.settings") as mock_settings:
            mock_settings.xai_api_key = ""
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Gemini result about restaurants in Almaty"
            gemini_searcher.assert_called_once()

    async def test_empty_synthesis_falls_back_to_gemini(self, gemini_searcher):
        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.research.dual_search._grok_web_search",
                new_callable=AsyncMock,
                return_value="Grok result",
            ),
            patch(
                "src.core.research.dual_search._gemini_synthesize",
                new_callable=AsyncMock,
                return_value="   ",
            ),
        ):
            mock_settings.xai_api_key = "test-key"
            mock_settings.ff_dual_search = True

            result = await dual_search(
                "test", "en", "",
                gemini_searcher=gemini_searcher,
            )

            assert result == "Gemini result about restaurants in Almaty"


class TestGrokModelConfig:
    async def test_grok_uses_configured_model(self):
        """_grok_web_search passes model from settings to the API."""
        mock_output_item = MagicMock()
        mock_output_item.text = "search result"
        mock_response = MagicMock()
        mock_response.output = [mock_output_item]

        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.llm.clients.xai_client",
                return_value=mock_client,
            ),
        ):
            mock_settings.grok_dual_search_model = (
                "grok-4.20-experimental-beta-0304-reasoning"
            )
            from src.core.research.dual_search import _grok_web_search

            result = await _grok_web_search("test query", "en")

            call_kwargs = mock_client.responses.create.call_args
            assert call_kwargs.kwargs["model"] == "grok-4.20-experimental-beta-0304-reasoning"
            assert result == "search result"

    async def test_grok_model_rollback(self):
        """Rollback to old model via settings works correctly."""
        mock_output_item = MagicMock()
        mock_output_item.text = "rollback result"
        mock_response = MagicMock()
        mock_response.output = [mock_output_item]

        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("src.core.research.dual_search.settings") as mock_settings,
            patch(
                "src.core.llm.clients.xai_client",
                return_value=mock_client,
            ),
        ):
            mock_settings.grok_dual_search_model = "grok-4-1-fast-reasoning"
            from src.core.research.dual_search import _grok_web_search

            result = await _grok_web_search("test query", "ru")

            call_kwargs = mock_client.responses.create.call_args
            assert call_kwargs.kwargs["model"] == "grok-4-1-fast-reasoning"
            assert result == "rollback result"
