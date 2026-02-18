"""MCP (Model Context Protocol) integration — Supabase hosted MCP Server.

Provides an MCP-powered analytics agent that can query the database
via the hosted Supabase MCP endpoint (https://mcp.supabase.com/mcp).
Gracefully degrades when pydantic-ai MCP or credentials are unavailable.
"""

import logging
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from src.core.config import settings
from src.core.observability import observe

logger = logging.getLogger(__name__)

MCP_BASE_URL = "https://mcp.supabase.com/mcp"


class AnalyticsResponse(BaseModel):
    """Structured response from analytics MCP agent."""

    answer: str = Field(description="Answer to the user's analytics question")
    data: dict[str, Any] = Field(default_factory=dict, description="Extracted data")
    sql_used: str | None = Field(None, description="SQL query used (if any)")


def _build_mcp_url() -> str:
    """Build Supabase MCP URL with project_ref and read_only params."""
    params: dict[str, str] = {"read_only": "true"}
    ref = settings.mcp_project_ref
    if ref:
        params["project_ref"] = ref
    return f"{MCP_BASE_URL}?{urlencode(params)}"


def get_supabase_mcp_server():
    """Create hosted Supabase MCP server instance for Pydantic AI.

    Uses MCPServerStreamableHTTP to connect to https://mcp.supabase.com/mcp.
    Returns None if pydantic-ai MCP support is not available or
    if credentials are missing.
    """
    try:
        from pydantic_ai.mcp import MCPServerStreamableHTTP
    except ImportError:
        logger.warning("pydantic-ai MCP not available, falling back to direct DB")
        return None

    if not settings.supabase_access_token:
        logger.warning("SUPABASE_ACCESS_TOKEN not configured, MCP server unavailable")
        return None

    try:
        return MCPServerStreamableHTTP(
            url=_build_mcp_url(),
            headers={
                "Authorization": f"Bearer {settings.supabase_access_token}",
            },
            timeout=5.0,
        )
    except Exception as e:
        logger.warning("MCP server creation failed: %s", e)
        return None


@observe(name="mcp_analytics_query")
async def run_analytics_query(query: str, family_id: str) -> AnalyticsResponse:
    """Run an analytics query via MCP-powered Pydantic AI agent.

    Args:
        query: The user's analytics question in natural language.
        family_id: Family ID to scope database queries (security boundary).

    Returns:
        AnalyticsResponse with the answer, extracted data, and SQL used.
    """
    try:
        from pydantic_ai import Agent
    except ImportError:
        logger.warning("pydantic-ai not available for MCP analytics")
        return AnalyticsResponse(
            answer="MCP сервер недоступен. Используйте стандартную статистику.",
            data={},
        )

    mcp_server = get_supabase_mcp_server()
    if mcp_server is None:
        return AnalyticsResponse(
            answer="MCP сервер недоступен. Используйте стандартную статистику.",
            data={},
        )

    try:
        agent = Agent(
            "anthropic:claude-sonnet-4-6",
            result_type=AnalyticsResponse,
            mcp_servers=[mcp_server],
            system_prompt=(
                f"You are a financial analytics agent. "
                f"All SQL queries MUST include WHERE family_id = '{family_id}'. "
                f"NEVER access data from other families. "
                f"NEVER run INSERT, UPDATE, DELETE, or DROP statements. "
                f"Answer in Russian."
            ),
        )

        async with agent.run_mcp_servers():
            result = await agent.run(query)
            return result.data

    except Exception as e:
        logger.error("MCP analytics query failed: %s", e)
        return AnalyticsResponse(
            answer="Произошла ошибка при выполнении запроса.",
            data={},
        )
