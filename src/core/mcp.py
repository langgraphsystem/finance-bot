"""MCP (Model Context Protocol) integration — Supabase MCP Server.

Provides an MCP-powered analytics agent that can query the database
via the Supabase MCP Server. Gracefully degrades when pydantic-ai MCP
or npx are unavailable.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.config import settings
from src.core.observability import observe

logger = logging.getLogger(__name__)


class AnalyticsResponse(BaseModel):
    """Structured response from analytics MCP agent."""

    answer: str = Field(description="Answer to the user's analytics question")
    data: dict[str, Any] = Field(default_factory=dict, description="Extracted data")
    sql_used: str | None = Field(None, description="SQL query used (if any)")


def get_supabase_mcp_server():
    """Create Supabase MCP server instance for Pydantic AI.

    Returns None if pydantic-ai MCP support is not available or
    if the server cannot be created for any reason.
    """
    try:
        from pydantic_ai.mcp import MCPServerStdio
    except ImportError:
        logger.warning("pydantic-ai MCP not available, falling back to direct DB")
        return None

    # Use service key for server-side access; fall back to regular key
    service_key = settings.supabase_service_key or settings.supabase_key

    if not settings.supabase_url or not service_key:
        logger.warning("Supabase URL or key not configured, MCP server unavailable")
        return None

    try:
        return MCPServerStdio(
            "npx",
            ["-y", "@supabase/mcp-server"],
            env={
                "SUPABASE_URL": settings.supabase_url,
                "SUPABASE_SERVICE_KEY": service_key,
            },
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
            "anthropic:claude-sonnet-4-5-20250929",
            result_type=AnalyticsResponse,
            mcp_servers=[mcp_server],
            system_prompt=(
                f"You are a financial analytics agent. "
                f"Query the database for family_id='{family_id}' only. "
                f"Never access data from other families. "
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
