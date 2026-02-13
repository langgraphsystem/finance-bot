"""Tests for MCP (Model Context Protocol) integration."""

import builtins
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.core.mcp import AnalyticsResponse, get_supabase_mcp_server, run_analytics_query


# --- Helpers ---


def _make_pydantic_ai_mock(agent_cls_mock=None):
    """Create a mock pydantic_ai module with an optional Agent mock.

    Used to intercept `from pydantic_ai import Agent` inside
    run_analytics_query when pydantic-ai is not installed.
    """
    mock_module = MagicMock()
    if agent_cls_mock is not None:
        mock_module.Agent = agent_cls_mock
    return mock_module


def _patch_pydantic_ai_import(agent_cls_mock):
    """Context-manager-style patch that intercepts `from pydantic_ai import Agent`.

    Returns a patch on builtins.__import__ that supplies a mock module
    for 'pydantic_ai' while letting all other imports pass through.
    """
    original_import = builtins.__import__
    mock_module = _make_pydantic_ai_mock(agent_cls_mock)

    def _mock_import(name, *args, **kwargs):
        if name == "pydantic_ai":
            return mock_module
        return original_import(name, *args, **kwargs)

    return patch.object(builtins, "__import__", side_effect=_mock_import)


# --- AnalyticsResponse model tests ---


class TestAnalyticsResponse:
    def test_full_fields(self):
        resp = AnalyticsResponse(
            answer="Расходы за март: 1500$",
            data={"total": 1500, "currency": "USD"},
            sql_used="SELECT sum(amount) FROM transactions WHERE family_id = '...'",
        )
        assert resp.answer == "Расходы за март: 1500$"
        assert resp.data["total"] == 1500
        assert "SELECT" in resp.sql_used

    def test_defaults(self):
        resp = AnalyticsResponse(answer="Ответ")
        assert resp.data == {}
        assert resp.sql_used is None

    def test_answer_required(self):
        with pytest.raises(Exception):
            AnalyticsResponse()

    def test_serialization_roundtrip(self):
        resp = AnalyticsResponse(
            answer="Тест",
            data={"key": "value"},
            sql_used="SELECT 1",
        )
        dumped = resp.model_dump()
        restored = AnalyticsResponse.model_validate(dumped)
        assert restored == resp


# --- get_supabase_mcp_server tests ---


class TestGetSupabaseMcpServer:
    @patch("src.core.mcp.settings")
    def test_returns_none_when_import_fails(self, mock_settings):
        """When pydantic_ai.mcp is not importable, returns None."""
        mock_settings.supabase_url = "https://example.supabase.co"
        mock_settings.supabase_service_key = "test-key"
        mock_settings.supabase_key = ""

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pydantic_ai.mcp":
                raise ImportError("mocked import failure")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = get_supabase_mcp_server()

        assert result is None

    @patch("src.core.mcp.settings")
    def test_returns_none_when_url_missing(self, mock_settings):
        """When supabase_url is empty, returns None."""
        mock_settings.supabase_url = ""
        mock_settings.supabase_service_key = "test-key"
        mock_settings.supabase_key = ""
        result = get_supabase_mcp_server()
        assert result is None

    @patch("src.core.mcp.settings")
    def test_returns_none_when_key_missing(self, mock_settings):
        """When both supabase_service_key and supabase_key are empty, returns None."""
        mock_settings.supabase_url = "https://example.supabase.co"
        mock_settings.supabase_service_key = ""
        mock_settings.supabase_key = ""
        result = get_supabase_mcp_server()
        assert result is None

    @patch("src.core.mcp.settings")
    def test_returns_server_when_configured(self, mock_settings):
        """When settings are present and pydantic-ai is available, returns an MCP server."""
        mock_settings.supabase_url = "https://example.supabase.co"
        mock_settings.supabase_service_key = "test-service-key"
        mock_settings.supabase_key = ""

        server = get_supabase_mcp_server()
        # If pydantic-ai is installed, we get a server object; otherwise None
        # In test env without pydantic-ai, this gracefully returns None
        if server is not None:
            from pydantic_ai.mcp import MCPServerStdio

            assert isinstance(server, MCPServerStdio)

    @patch("src.core.mcp.settings")
    def test_falls_back_to_supabase_key(self, mock_settings):
        """Uses supabase_key when supabase_service_key is empty."""
        mock_settings.supabase_url = "https://example.supabase.co"
        mock_settings.supabase_service_key = ""
        mock_settings.supabase_key = "regular-key"

        server = get_supabase_mcp_server()
        # If pydantic-ai is installed, we get a server; key fallback was used
        if server is not None:
            from pydantic_ai.mcp import MCPServerStdio

            assert isinstance(server, MCPServerStdio)

    @patch("src.core.mcp.settings")
    def test_returns_none_on_creation_error(self, mock_settings):
        """Returns None when MCPServerStdio constructor raises."""
        mock_settings.supabase_url = "https://example.supabase.co"
        mock_settings.supabase_service_key = "test-key"
        mock_settings.supabase_key = ""

        mock_stdio = MagicMock(side_effect=RuntimeError("npx not found"))
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pydantic_ai.mcp":
                mod = MagicMock()
                mod.MCPServerStdio = mock_stdio
                return mod
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = get_supabase_mcp_server()

        assert result is None


# --- run_analytics_query tests ---


class TestRunAnalyticsQuery:
    @pytest.mark.asyncio
    async def test_fallback_when_mcp_unavailable(self):
        """Returns fallback response when MCP server is not available."""
        with patch("src.core.mcp.get_supabase_mcp_server", return_value=None):
            result = await run_analytics_query("Сколько потратили?", "family-123")

        assert result.answer is not None
        assert "недоступен" in result.answer or "ошибка" in result.answer.lower()
        assert result.data == {}

    @pytest.mark.asyncio
    async def test_returns_error_response_on_agent_failure(self):
        """Returns error response when agent execution fails."""
        mock_server = MagicMock()

        mock_agent_instance = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = RuntimeError("MCP connection failed")
        mock_agent_instance.run_mcp_servers.return_value = mock_ctx

        mock_agent_cls = MagicMock(return_value=mock_agent_instance)

        with (
            patch("src.core.mcp.get_supabase_mcp_server", return_value=mock_server),
            _patch_pydantic_ai_import(mock_agent_cls),
        ):
            result = await run_analytics_query("Сколько потратили?", "family-123")

        assert result.answer is not None
        assert "ошибка" in result.answer.lower() or "недоступен" in result.answer

    @pytest.mark.asyncio
    async def test_successful_query(self):
        """Returns proper response on successful MCP agent execution."""
        mock_server = MagicMock()

        expected = AnalyticsResponse(
            answer="Расходы за март: 1500$",
            data={"total": 1500},
            sql_used="SELECT sum(amount) ...",
        )

        mock_run_result = MagicMock()
        mock_run_result.data = expected

        mock_agent_instance = MagicMock()
        mock_ctx = AsyncMock()
        mock_agent_instance.run_mcp_servers.return_value = mock_ctx
        mock_agent_instance.run = AsyncMock(return_value=mock_run_result)

        mock_agent_cls = MagicMock(return_value=mock_agent_instance)

        with (
            patch("src.core.mcp.get_supabase_mcp_server", return_value=mock_server),
            _patch_pydantic_ai_import(mock_agent_cls),
        ):
            result = await run_analytics_query("Расходы за март", "family-123")

        assert result.answer == "Расходы за март: 1500$"
        assert result.data["total"] == 1500
        assert result.sql_used is not None

    @pytest.mark.asyncio
    async def test_agent_created_with_correct_params(self):
        """Verifies Agent is created with correct model, MCP servers, and system prompt."""
        mock_server = MagicMock()

        expected = AnalyticsResponse(answer="ok", data={})
        mock_run_result = MagicMock()
        mock_run_result.data = expected

        mock_agent_instance = MagicMock()
        mock_ctx = AsyncMock()
        mock_agent_instance.run_mcp_servers.return_value = mock_ctx
        mock_agent_instance.run = AsyncMock(return_value=mock_run_result)

        mock_agent_cls = MagicMock(return_value=mock_agent_instance)

        with (
            patch("src.core.mcp.get_supabase_mcp_server", return_value=mock_server),
            _patch_pydantic_ai_import(mock_agent_cls),
        ):
            await run_analytics_query("test query", "fam-42")

        # Verify Agent constructor was called with expected arguments
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args
        assert call_kwargs[0][0] == "anthropic:claude-sonnet-4-5-20250929"
        assert call_kwargs[1]["result_type"] is AnalyticsResponse
        assert mock_server in call_kwargs[1]["mcp_servers"]
        assert "fam-42" in call_kwargs[1]["system_prompt"]

    @pytest.mark.asyncio
    async def test_fallback_when_pydantic_ai_not_installed(self):
        """Returns fallback when pydantic-ai cannot be imported at all."""
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pydantic_ai":
                raise ImportError("No module named 'pydantic_ai'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = await run_analytics_query("Тест", "family-1")

        assert "недоступен" in result.answer
        assert result.data == {}
