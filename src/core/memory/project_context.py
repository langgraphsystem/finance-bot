"""Project context loader for context assembly (Phase 12, Layer 0.75).

Loads the active project name, description, and project-specific Mem0 facts
into the system prompt so the bot knows which project the user is working on
and has relevant context for that project.
"""

import logging

logger = logging.getLogger(__name__)


async def get_active_project_block(user_id: str) -> str:
    """Load the active project for the user and format as context block.

    Includes project metadata + project-specific Mem0 facts (up to 5).
    Returns empty string if no active project.
    """
    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.models.user_context import UserContext
    from src.core.models.user_project import UserProject

    try:
        async with async_session() as session:
            # Get active project id from user context
            ctx_result = await session.execute(
                select(UserContext.active_project_id).where(
                    UserContext.user_id == user_id
                )
            )
            active_project_id = ctx_result.scalar_one_or_none()

            if not active_project_id:
                return ""

            # Load project details
            proj_result = await session.execute(
                select(UserProject).where(UserProject.id == active_project_id)
            )
            project = proj_result.scalar_one_or_none()

            if not project:
                return ""

            # Load project-specific Mem0 facts
            project_facts = await _load_project_facts(user_id, project.name)

            return _format_project_block(
                project.name, project.description, project.status, project_facts,
            )
    except Exception as e:
        logger.debug("Active project load failed: %s", e)
        return ""


async def _load_project_facts(user_id: str, project_name: str) -> list[str]:
    """Search Mem0 for facts related to the active project."""
    try:
        from src.core.memory.mem0_client import search_memories
        from src.core.memory.mem0_domains import MemoryDomain

        results = await search_memories(
            query=project_name,
            user_id=user_id,
            limit=5,
            domain=MemoryDomain.projects,
        )
        return [
            m.get("memory", m.get("text", ""))
            for m in results
            if m.get("memory") or m.get("text")
        ]
    except Exception as e:
        logger.debug("Project facts load failed: %s", e)
        return []


def _format_project_block(
    name: str,
    description: str | None,
    status: str,
    facts: list[str] | None = None,
) -> str:
    """Format project info + facts as an XML-tagged context block."""
    lines = [f"Active project: {name} (status: {status})"]
    if description:
        lines.append(f"Description: {description}")
    if facts:
        lines.append("Project context:")
        for fact in facts:
            lines.append(f"  - {fact}")
    content = "\n".join(lines)
    return f"<active_project>\n{content}\n</active_project>"
