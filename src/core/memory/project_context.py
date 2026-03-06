"""Project context loader for context assembly (Phase 12, Layer 0.75).

Loads the active project name and description into system prompt
so the bot knows which project the user is currently working on.
"""

import logging

logger = logging.getLogger(__name__)


async def get_active_project_block(user_id: str) -> str:
    """Load the active project for the user and format as context block.

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

            return _format_project_block(project.name, project.description, project.status)
    except Exception as e:
        logger.debug("Active project load failed: %s", e)
        return ""


def _format_project_block(name: str, description: str | None, status: str) -> str:
    """Format project info as an XML-tagged context block."""
    lines = [f"Active project: {name} (status: {status})"]
    if description:
        lines.append(f"Description: {description}")
    content = "\n".join(lines)
    return f"<active_project>\n{content}\n</active_project>"
