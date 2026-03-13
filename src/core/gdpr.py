"""GDPR compliance — export, delete, rectify user data."""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import redis
from src.core.memory.mem0_client import get_all_memories
from src.core.memory.registry import clear_memory_registry, export_memory_registry
from src.core.models.audit import AuditLog
from src.core.models.booking import Booking
from src.core.models.contact import Contact
from src.core.models.conversation import ConversationMessage
from src.core.models.document import Document
from src.core.models.document_embedding import DocumentEmbedding
from src.core.models.life_event import LifeEvent
from src.core.models.scheduled_action import ScheduledAction
from src.core.models.session_summary import SessionSummary
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.models.user_context import UserContext
from src.core.models.user_profile import UserProfile
from src.core.models.user_project import UserProject

logger = logging.getLogger(__name__)


class MemoryGDPR:
    """GDPR operations for user data."""

    async def export_user_data(self, session: AsyncSession, user_id: str) -> dict:
        """GDPR Art. 15: Right of access — export all user data."""
        uid = uuid.UUID(user_id)

        # Transactions
        tx_result = await session.execute(select(Transaction).where(Transaction.user_id == uid))
        transactions = [
            {
                "id": str(t.id),
                "type": t.type.value,
                "amount": float(t.amount),
                "merchant": t.merchant,
                "date": t.date.isoformat(),
                "scope": t.scope.value,
            }
            for t in tx_result.scalars()
        ]

        # Conversation logs
        msg_result = await session.execute(
            select(ConversationMessage).where(ConversationMessage.user_id == uid)
        )
        messages = [
            {
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msg_result.scalars()
        ]

        # Mem0 memories
        try:
            memories = await get_all_memories(user_id)
        except Exception:
            memories = []
        try:
            memory_registry = await export_memory_registry(user_id, session=session)
        except Exception:
            memory_registry = []

        profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == uid))

        summary_result = await session.execute(
            select(SessionSummary).where(SessionSummary.user_id == uid)
        )
        summaries = [
            {
                "id": s.id,
                "session_id": str(s.session_id),
                "summary": s.summary,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in summary_result.scalars()
        ]

        life_result = await session.execute(select(LifeEvent).where(LifeEvent.user_id == uid))
        life_events = [
            {
                "id": str(event.id),
                "type": str(event.type),
                "date": event.date.isoformat(),
                "text": event.text,
            }
            for event in life_result.scalars()
        ]

        task_result = await session.execute(select(Task).where(Task.user_id == uid))
        tasks = [
            {
                "id": str(task.id),
                "title": task.title,
                "status": str(task.status),
                "visibility": task.visibility,
            }
            for task in task_result.scalars()
        ]

        scheduled_result = await session.execute(
            select(ScheduledAction).where(ScheduledAction.user_id == uid)
        )
        scheduled_actions = [
            {
                "id": str(action.id),
                "title": action.title,
                "status": str(action.status),
            }
            for action in scheduled_result.scalars()
        ]

        project_result = await session.execute(
            select(UserProject).where(UserProject.user_id == uid)
        )
        projects = [
            {
                "id": str(project.id),
                "name": project.name,
                "status": str(project.status),
            }
            for project in project_result.scalars()
        ]

        contact_result = await session.execute(select(Contact).where(Contact.user_id == uid))
        contacts = [
            {
                "id": str(contact.id),
                "name": contact.name,
                "role": str(contact.role),
            }
            for contact in contact_result.scalars()
        ]

        booking_result = await session.execute(select(Booking).where(Booking.user_id == uid))
        bookings = [
            {
                "id": str(booking.id),
                "title": booking.title,
                "status": str(booking.status),
            }
            for booking in booking_result.scalars()
        ]

        document_result = await session.execute(select(Document).where(Document.user_id == uid))
        documents = [
            {
                "id": str(doc.id),
                "title": doc.title,
                "file_name": doc.file_name,
                "visibility": doc.visibility,
            }
            for doc in document_result.scalars()
        ]

        return {
            "user_id": user_id,
            "transactions": transactions,
            "conversation_logs": messages,
            "memories": memories,
            "memory_registry": memory_registry,
            "profile": {
                "core_identity": profile.core_identity if profile else None,
                "active_rules": profile.active_rules if profile else None,
                "learned_patterns": profile.learned_patterns if profile else None,
            },
            "session_summaries": summaries,
            "life_events": life_events,
            "tasks": tasks,
            "scheduled_actions": scheduled_actions,
            "projects": projects,
            "contacts": contacts,
            "bookings": bookings,
            "documents": documents,
        }

    async def delete_user_data(self, session: AsyncSession, user_id: str) -> bool:
        """GDPR Art. 17: Right to erasure — delete all user data."""
        uid = uuid.UUID(user_id)
        document_ids = list(
            (
                await session.execute(select(Document.id).where(Document.user_id == uid))
            ).scalars()
        )

        # Delete from PostgreSQL
        await session.execute(delete(ConversationMessage).where(ConversationMessage.user_id == uid))
        await session.execute(delete(Transaction).where(Transaction.user_id == uid))
        await session.execute(delete(AuditLog).where(AuditLog.user_id == uid))
        await session.execute(delete(UserContext).where(UserContext.user_id == uid))
        try:
            await clear_memory_registry(
                user_id,
                session=session,
                include_stores={"mem0", "identity", "rule", "summary"},
            )
        except Exception as e:
            logger.warning("Memory registry deletion failed: %s", e)
        await session.execute(delete(UserProfile).where(UserProfile.user_id == uid))
        await session.execute(delete(LifeEvent).where(LifeEvent.user_id == uid))
        await session.execute(delete(Task).where(Task.user_id == uid))
        await session.execute(delete(ScheduledAction).where(ScheduledAction.user_id == uid))
        await session.execute(delete(UserProject).where(UserProject.user_id == uid))
        await session.execute(delete(Contact).where(Contact.user_id == uid))
        await session.execute(delete(Booking).where(Booking.user_id == uid))
        if document_ids:
            await session.execute(
                delete(DocumentEmbedding).where(DocumentEmbedding.document_id.in_(document_ids))
            )
        await session.execute(delete(Document).where(Document.user_id == uid))
        await session.commit()

        # Delete from Redis
        try:
            keys = []
            for pattern in (
                f"conv:{user_id}:*",
                f"session_facts:{user_id}",
                f"proc_rt:{user_id}:*",
                f"mem0_dlq:{user_id}",
                f"mem0_dlq_idem:{user_id}",
                f"core_identity:{user_id}",
            ):
                async for key in redis.scan_iter(match=pattern):
                    keys.append(key)
            if keys:
                await redis.delete(*keys)
        except Exception as e:
            logger.warning("Redis deletion failed: %s", e)

        logger.info("All data deleted for user %s", user_id)
        return True

    async def rectify_memory(self, user_id: str, old: str, new: str) -> None:
        """GDPR Art. 16: Right to rectification."""
        from src.core.memory.mem0_client import get_memory

        memory = get_memory()
        results = memory.search(old, user_id=user_id, limit=5)
        result_list = results.get("results", []) if isinstance(results, dict) else results
        for mem in result_list:
            memory.update(mem["id"], new)
        logger.info("Rectified memory for user %s: '%s' → '%s'", user_id, old, new)
