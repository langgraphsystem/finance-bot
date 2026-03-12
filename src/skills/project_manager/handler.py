"""Skill: project_manager — create, switch, and list user projects (Phase 12).

Handles: "создай проект X", "это про Титан", "мои проекты",
"start project called Y", "switch to project Z", "list projects".
"""

import logging
import uuid

from src.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)

_STATUS_EMOJI = {
    "active": "",
    "paused": "[paused]",
    "completed": "[done]",
    "archived": "[archived]",
}


class ProjectManagerSkill(BaseSkill):
    name = "project_manager"
    intents = ["set_project", "create_project", "list_projects"]
    model = "gemini-3.1-flash-lite-preview"

    def get_system_prompt(self, context) -> str:  # noqa: ANN001, ARG002
        return ""

    async def execute(self, message, context, intent_data=None) -> SkillResult:  # noqa: ANN001
        intent = (intent_data or {}).get("_intent", "list_projects")
        language = context.language or "en"

        if intent == "create_project":
            return await self._handle_create(message, context, intent_data, language)
        if intent == "set_project":
            return await self._handle_set_active(message, context, intent_data, language)
        return await self._handle_list(context, language)

    # ------------------------------------------------------------------
    # Create project
    # ------------------------------------------------------------------
    async def _handle_create(self, message, context, intent_data, language):  # noqa: ANN001
        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_project import UserProject

        project_name = (
            (intent_data or {}).get("project_name")
            or _extract_project_name(message.text or "")
        )
        if not project_name or not project_name.strip():
            return SkillResult(response_text=_msg("empty", language))

        project_name = project_name.strip()
        user_id = context.user_id

        try:
            async with async_session() as session:
                # Check duplicate
                existing = await session.execute(
                    select(UserProject).where(
                        UserProject.user_id == user_id,
                        UserProject.name == project_name,
                        UserProject.status != "archived",
                    )
                )
                if existing.scalar_one_or_none():
                    return SkillResult(
                        response_text=_msg("duplicate", language, name=project_name),
                    )

                # Create
                project = UserProject(
                    family_id=context.family_id,
                    user_id=user_id,
                    name=project_name,
                )
                session.add(project)
                await session.flush()
                project_id = project.id
                await session.commit()

            # Set as active
            await _set_active_project(user_id, project_id)

            # Save to Mem0 projects domain
            background_tasks = [
                _mem0_save_project(str(user_id), project_name),
            ]

            return SkillResult(
                response_text=_msg("created", language, name=project_name),
                background_tasks=background_tasks,
            )
        except Exception as e:
            logger.error("Create project failed: %s", e)
            return SkillResult(response_text=_msg("error", language))

    # ------------------------------------------------------------------
    # Set active project
    # ------------------------------------------------------------------
    async def _handle_set_active(self, message, context, intent_data, language):  # noqa: ANN001
        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_project import UserProject
        from src.core.text_utils import is_similar

        project_name = (
            (intent_data or {}).get("project_name")
            or _extract_project_name(message.text or "")
        )
        if not project_name or not project_name.strip():
            return SkillResult(response_text=_msg("empty", language))

        project_name = project_name.strip()
        user_id = context.user_id

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(UserProject).where(
                        UserProject.user_id == user_id,
                        UserProject.status.in_(["active", "paused"]),
                    )
                )
                projects = result.scalars().all()

            if not projects:
                return SkillResult(
                    response_text=_msg("not_found_create", language, name=project_name),
                    buttons=[{
                        "text": _btn("create", language),
                        "callback_data": f"project:create:{project_name[:50]}",
                    }],
                )

            # Exact match first
            for p in projects:
                if p.name.lower() == project_name.lower():
                    await _set_active_project(user_id, p.id)
                    return SkillResult(
                        response_text=_msg("switched", language, name=p.name),
                    )

            # Fuzzy match
            matches = [p for p in projects if is_similar(p.name, project_name, threshold=0.6)]

            if len(matches) == 1:
                await _set_active_project(user_id, matches[0].id)
                return SkillResult(
                    response_text=_msg("switched", language, name=matches[0].name),
                )

            if len(matches) > 1:
                buttons = [
                    {"text": p.name, "callback_data": f"project:set:{p.id}"}
                    for p in matches[:5]
                ]
                return SkillResult(
                    response_text=_msg("disambiguate", language),
                    buttons=buttons,
                )

            # No matches
            return SkillResult(
                response_text=_msg("not_found_create", language, name=project_name),
                buttons=[{
                    "text": _btn("create", language),
                    "callback_data": f"project:create:{project_name[:50]}",
                }],
            )
        except Exception as e:
            logger.error("Set active project failed: %s", e)
            return SkillResult(response_text=_msg("error", language))

    # ------------------------------------------------------------------
    # List projects
    # ------------------------------------------------------------------
    async def _handle_list(self, context, language):  # noqa: ANN001
        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_context import UserContext
        from src.core.models.user_project import UserProject

        user_id = context.user_id

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(UserProject)
                    .where(
                        UserProject.user_id == user_id,
                        UserProject.status != "archived",
                    )
                    .order_by(UserProject.updated_at.desc())
                )
                projects = result.scalars().all()

                # Get active project id
                ctx_result = await session.execute(
                    select(UserContext.active_project_id).where(
                        UserContext.user_id == user_id
                    )
                )
                active_id = ctx_result.scalar_one_or_none()

            if not projects:
                return SkillResult(response_text=_msg("list_empty", language))

            lines = []
            for p in projects:
                marker = " *" if active_id and p.id == active_id else ""
                status = _STATUS_EMOJI.get(p.status, "")
                desc = f" — {p.description[:60]}" if p.description else ""
                lines.append(f"<b>{p.name}</b>{marker} {status}{desc}")

            header = _msg("list_header", language, count=str(len(projects)))
            body = "\n".join(lines)
            footer = _msg("list_footer", language) if active_id else ""

            return SkillResult(response_text=f"{header}\n\n{body}\n\n{footer}".strip())
        except Exception as e:
            logger.error("List projects failed: %s", e)
            return SkillResult(response_text=_msg("error", language))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _set_active_project(user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Update UserContext to set the active project."""
    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.models.user_context import UserContext
    from src.core.models.user_project import UserProject

    async with async_session() as session:
        project_result = await session.execute(
            select(UserProject.family_id).where(
                UserProject.id == project_id,
                UserProject.user_id == user_id,
            )
        )
        family_id = project_result.scalar_one_or_none()
        if not family_id:
            return

        ctx_result = await session.execute(
            select(UserContext).where(UserContext.user_id == user_id)
        )
        user_context = ctx_result.scalar_one_or_none()

        if user_context:
            user_context.active_project_id = project_id
        else:
            session.add(
                UserContext(
                    user_id=user_id,
                    family_id=family_id,
                    active_project_id=project_id,
                )
            )
        await session.commit()


async def _mem0_save_project(user_id: str, project_name: str) -> None:
    """Save project to Mem0 projects domain."""
    try:
        from src.core.memory.mem0_client import add_memory

        await add_memory(
            f"User project: {project_name}",
            user_id=user_id,
            source="project_manager",
            category="user_project",
            memory_type="project_reference",
        )
    except Exception as e:
        logger.warning("Mem0 project save failed: %s", e)


async def handle_project_callback(callback_data: str, user_id: uuid.UUID, language: str) -> str:
    """Handle project: callbacks from inline buttons.

    Returns response text to send back.
    """
    parts = callback_data.split(":", 2)
    if len(parts) < 3:
        return _msg("error", language)

    action = parts[1]
    value = parts[2]

    if action == "set":
        try:
            project_id = uuid.UUID(value)
        except ValueError:
            return _msg("error", language)

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_project import UserProject

        async with async_session() as session:
            result = await session.execute(
                select(UserProject).where(UserProject.id == project_id)
            )
            project = result.scalar_one_or_none()

        if not project:
            return _msg("error", language)

        await _set_active_project(user_id, project_id)
        return _msg("switched", language, name=project.name)

    if action == "create":
        project_name = value.strip()
        if not project_name:
            return _msg("empty", language)

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.user_context import UserContext
        from src.core.models.user_project import UserProject

        async with async_session() as session:
            ctx_result = await session.execute(
                select(UserContext.family_id).where(UserContext.user_id == user_id)
            )
            family_id = ctx_result.scalar_one_or_none()

        if not family_id:
            return _msg("error", language)

        async with async_session() as session:
            project = UserProject(
                family_id=family_id,
                user_id=user_id,
                name=project_name,
            )
            session.add(project)
            await session.flush()
            project_id = project.id
            await session.commit()

        await _set_active_project(user_id, project_id)
        await _mem0_save_project(str(user_id), project_name)
        return _msg("created", language, name=project_name)

    return _msg("error", language)


def _extract_project_name(text: str) -> str:
    """Extract project name from message text."""
    lower = text.lower()
    patterns = [
        "это про ", "переключись на проект ", "переключись на ",
        "про проект ", "проект ", "работаем над ",
        "switch to project ", "work on project ", "work on ",
        "switch to ", "project called ", "start project ",
        "создай проект ", "новый проект ",
    ]
    for p in patterns:
        if p in lower:
            idx = lower.index(p) + len(p)
            return text[idx:].strip().strip(".,!\"'")
    return text.strip()


def _msg(key: str, language: str, **kwargs: str) -> str:
    """Get a localized message."""
    is_ru = language and language.startswith("ru")

    messages = {
        "empty": {
            "ru": "Укажите название проекта.",
            "en": "Please specify a project name.",
        },
        "duplicate": {
            "ru": "Проект <b>{name}</b> уже существует.",
            "en": "Project <b>{name}</b> already exists.",
        },
        "created": {
            "ru": "Проект <b>{name}</b> создан и активирован.",
            "en": "Project <b>{name}</b> created and activated.",
        },
        "switched": {
            "ru": "Переключился на проект <b>{name}</b>.",
            "en": "Switched to project <b>{name}</b>.",
        },
        "not_found_create": {
            "ru": "Проект <b>{name}</b> не найден. Создать?",
            "en": "Project <b>{name}</b> not found. Create it?",
        },
        "disambiguate": {
            "ru": "Найдено несколько проектов. Какой?",
            "en": "Multiple projects found. Which one?",
        },
        "list_empty": {
            "ru": "У вас пока нет проектов.",
            "en": "You don't have any projects yet.",
        },
        "list_header": {
            "ru": "Ваши проекты ({count}):",
            "en": "Your projects ({count}):",
        },
        "list_footer": {
            "ru": "* — активный проект",
            "en": "* — active project",
        },
        "error": {
            "ru": "Не удалось выполнить операцию с проектом.",
            "en": "Failed to perform project operation.",
        },
    }

    lang_key = "ru" if is_ru else "en"
    template = messages.get(key, {}).get(lang_key, messages.get(key, {}).get("en", "OK"))
    return template.format(**kwargs)


def _btn(key: str, language: str) -> str:
    """Get a localized button label."""
    is_ru = language and language.startswith("ru")
    labels = {
        "create": ("Создать", "Create"),
    }
    ru, en = labels.get(key, ("OK", "OK"))
    return ru if is_ru else en


skill = ProjectManagerSkill()
