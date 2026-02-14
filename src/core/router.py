"""Message router — main orchestration: message → intent → skill → response."""

import asyncio
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from src.agents import AGENTS, AgentRouter
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.family import create_family
from src.core.guardrails import check_input
from src.core.intent import detect_intent
from src.core.memory import sliding_window
from src.core.memory.summarization import summarize_dialog
from src.core.models.conversation import ConversationMessage
from src.core.models.document import Document
from src.core.models.enums import (
    ConversationState,
    DocumentType,
    LoadStatus,
    MessageRole,
    Scope,
    TransactionType,
)
from src.core.models.load import Load
from src.core.models.transaction import Transaction
from src.core.models.user_context import UserContext
from src.core.rate_limit import check_rate_limit
from src.core.request_context import reset_family_context, set_family_context
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage
from src.skills import create_registry
from src.skills.base import SkillRegistry, SkillResult

logger = logging.getLogger(__name__)

_registry: SkillRegistry | None = None
_agent_router: AgentRouter | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = create_registry()
    return _registry


def get_agent_router() -> AgentRouter:
    """Lazy-init the AgentRouter (wraps SkillRegistry)."""
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter(AGENTS, get_registry())
    return _agent_router


async def _persist_message(
    user_id: str,
    family_id: str,
    role: MessageRole,
    content: str,
    intent: str | None = None,
) -> None:
    """Persist a conversation message to PostgreSQL."""
    try:
        async with async_session() as session:
            msg = ConversationMessage(
                user_id=uuid.UUID(user_id),
                family_id=uuid.UUID(family_id),
                session_id=uuid.uuid4(),
                role=role,
                content=content,
                intent=intent,
            )
            session.add(msg)
            await session.commit()
    except Exception as e:
        logger.warning("Failed to persist conversation message: %s", e)


async def handle_message(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Main message handler: intent detection → skill execution → response."""
    registry = get_registry()

    if not await check_rate_limit(message.user_id):
        return OutgoingMessage(
            text="Слишком много сообщений. Подождите минуту.",
            chat_id=message.chat_id,
        )

    # Set RLS family context so that any DB session opened downstream
    # (inside skills, agents, etc.) automatically applies the correct
    # ``app.current_family_id`` PostgreSQL setting.
    token = set_family_context(context.family_id) if context.family_id else None
    try:
        return await _dispatch_message(message, context, registry)
    finally:
        if token is not None:
            reset_family_context(token)


async def _dispatch_message(
    message: IncomingMessage,
    context: SessionContext,
    registry: SkillRegistry,
) -> OutgoingMessage:
    """Inner dispatch logic extracted from *handle_message* for clean RLS wrapping."""

    # Handle callbacks immediately
    if message.type == MessageType.callback:
        return await _handle_callback(message, context)

    # Voice transcription: convert voice to text, then process as text
    if message.type == MessageType.voice:
        from src.core.voice import transcribe_voice

        if not message.voice_bytes:
            return OutgoingMessage(
                text="Не удалось получить голосовое сообщение.",
                chat_id=message.chat_id,
            )
        transcribed_text = await transcribe_voice(message.voice_bytes)
        if not transcribed_text:
            return OutgoingMessage(
                text="Не удалось распознать речь. Попробуйте ещё раз или напишите текстом.",
                chat_id=message.chat_id,
            )
        # Replace message with transcribed text and continue as text
        message = IncomingMessage(
            id=message.id,
            user_id=message.user_id,
            chat_id=message.chat_id,
            text=transcribed_text,
            type=MessageType.text,
            raw=message.raw,
        )

    # Handle photos and documents as scan_document
    if message.type in (MessageType.photo, MessageType.document):
        intent_name = "scan_document"
        intent_data: dict[str, Any] = {}
    else:
        # --- Guardrails check BEFORE intent detection ---
        if message.text:
            is_safe, refusal_text = await check_input(message.text)
            if not is_safe:
                return OutgoingMessage(
                    text=(
                        refusal_text
                        or "Я финансовый помощник. Могу помочь с учётом расходов и доходов."
                    ),
                    chat_id=message.chat_id,
                )

        # --- Slash commands (before intent detection) ---
        if message.text and message.text.startswith("/"):
            cmd_result = await _handle_slash_command(message, context)
            if cmd_result:
                return cmd_result

        # Intent detection
        result = await detect_intent(
            text=message.text or "",
            categories=context.categories,
            language=context.language,
        )
        intent_name = result.intent
        intent_data = result.data.model_dump() if result.data else {}
        intent_data["confidence"] = result.confidence
        logger.info(
            "Intent: %s (%.2f) for user %s",
            intent_name,
            result.confidence,
            context.user_id,
        )

    # Route through AgentRouter (agent -> context assembly -> skill)
    agent_router = get_agent_router()
    try:
        skill_result = await agent_router.route(intent_name, message, context, intent_data)
    except Exception as e:
        logger.error(
            "AgentRouter failed for %s: %s, falling back to direct skill",
            intent_name,
            e,
            exc_info=True,
        )
        # Fallback: direct skill dispatch (backward compatibility)
        try:
            skill = registry.get(intent_name)
            if not skill:
                skill = registry.get("general_chat")
            skill_result = await skill.execute(message, context, intent_data)
        except Exception as inner_e:
            logger.error("Fallback skill %s also failed: %s", intent_name, inner_e, exc_info=True)
            skill_result = SkillResult(response_text="Произошла ошибка. Попробуйте ещё раз.")

    # Save to sliding window (Redis) AND persist to PostgreSQL
    if message.text:
        await sliding_window.add_message(context.user_id, "user", message.text, intent_name)
        asyncio.create_task(
            _persist_message(
                context.user_id,
                context.family_id,
                MessageRole.user,
                message.text,
                intent_name,
            )
        )
    await sliding_window.add_message(context.user_id, "assistant", skill_result.response_text)
    asyncio.create_task(
        _persist_message(
            context.user_id,
            context.family_id,
            MessageRole.assistant,
            skill_result.response_text,
        )
    )

    # Layer 5: Trigger incremental dialog summarization in the background
    asyncio.create_task(summarize_dialog(context.user_id, context.family_id))

    # Execute background tasks (properly handle coroutines)
    for task_fn in skill_result.background_tasks:
        try:
            result = task_fn()
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception as e:
            logger.warning("Background task failed: %s", e)

    return OutgoingMessage(
        text=skill_result.response_text,
        chat_id=message.chat_id,
        buttons=skill_result.buttons,
        document=skill_result.document,
        document_name=skill_result.document_name,
        photo_url=skill_result.photo_url,
        chart_url=skill_result.chart_url,
    )


async def _handle_slash_command(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage | None:
    """Handle slash commands: /export, /delete_all, /invite."""
    text = (message.text or "").strip()

    if text == "/export":
        import json

        from src.core.gdpr import MemoryGDPR

        gdpr = MemoryGDPR()
        try:
            async with async_session() as session:
                data = await gdpr.export_user_data(session, context.user_id)
            json_bytes = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            return OutgoingMessage(
                text="Ваши данные:",
                chat_id=message.chat_id,
                document=json_bytes,
                document_name="my_data.json",
            )
        except Exception as e:
            logger.error("GDPR export failed: %s", e)
            return OutgoingMessage(text="Ошибка при экспорте данных.", chat_id=message.chat_id)

    elif text == "/delete_all":
        from src.core.gdpr import MemoryGDPR

        gdpr = MemoryGDPR()
        try:
            async with async_session() as session:
                await gdpr.delete_user_data(session, context.user_id)
            return OutgoingMessage(
                text="Все ваши данные удалены. Для нового старта отправьте /start",
                chat_id=message.chat_id,
            )
        except Exception as e:
            logger.error("GDPR delete failed: %s", e)
            return OutgoingMessage(text="Ошибка при удалении данных.", chat_id=message.chat_id)

    elif text.startswith("/invite"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return OutgoingMessage(
                text="Используйте: /invite КОД\nНапример: /invite ABC12345",
                chat_id=message.chat_id,
            )
        invite_code = parts[1].strip()
        from src.core.family import join_family

        try:
            telegram_id = int(message.user_id)
            owner_name = "User"
            if message.raw and hasattr(message.raw, "from_user"):
                from_user = message.raw.from_user
                if from_user and hasattr(from_user, "first_name") and from_user.first_name:
                    owner_name = from_user.first_name
            async with async_session() as session:
                result = await join_family(
                    session=session,
                    invite_code=invite_code,
                    telegram_id=telegram_id,
                    name=owner_name,
                    language=context.language,
                )
            if result:
                family, user = result
                return OutgoingMessage(
                    text=f"Вы присоединились к семье \u00ab{family.name}\u00bb!",
                    chat_id=message.chat_id,
                )
            else:
                return OutgoingMessage(
                    text="Неверный код приглашения или вы уже в семье.",
                    chat_id=message.chat_id,
                )
        except Exception as e:
            logger.error("Join family failed: %s", e)
            return OutgoingMessage(text="Ошибка при присоединении.", chat_id=message.chat_id)

    return None  # Not a known slash command — continue to intent detection


async def _set_onboarding_state(
    telegram_id: str,
    state: ConversationState,
) -> None:
    """Store onboarding sub-state in Redis for unregistered users."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        await redis.set(key, state.value, ex=3600)  # 1 hour TTL
    except Exception as e:
        logger.warning("Failed to set onboarding state in Redis: %s", e)


async def _get_onboarding_state(telegram_id: str) -> str:
    """Retrieve onboarding sub-state from Redis for unregistered users."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        value = await redis.get(key)
        return value if value else ""
    except Exception as e:
        logger.warning("Failed to get onboarding state from Redis: %s", e)
        return ""


async def _clear_onboarding_state(telegram_id: str) -> None:
    """Clear onboarding sub-state from Redis."""
    try:
        from src.core.db import redis

        key = f"onboarding_state:{telegram_id}"
        await redis.delete(key)
    except Exception as e:
        logger.warning("Failed to clear onboarding state from Redis: %s", e)


async def _handle_callback(
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Handle inline button callbacks."""
    data = message.callback_data or ""
    parts = data.split(":")

    if not parts:
        return OutgoingMessage(text="Неизвестная команда.", chat_id=message.chat_id)

    action = parts[0]

    if action == "confirm":
        # Acknowledge confirmation — transaction stays in DB as-is
        return OutgoingMessage(text="✅ Подтверждено!", chat_id=message.chat_id)

    elif action == "cancel":
        # Delete the transaction from DB
        tx_id = parts[1] if len(parts) > 1 else None
        if tx_id:
            try:
                async with async_session() as session:
                    await session.execute(
                        delete(Transaction).where(Transaction.id == uuid.UUID(tx_id))
                    )
                    await session.commit()
                logger.info("Transaction %s deleted by user %s", tx_id, context.user_id)
            except Exception as e:
                logger.error("Failed to delete transaction %s: %s", tx_id, e)
                return OutgoingMessage(
                    text="Ошибка при удалении транзакции.", chat_id=message.chat_id
                )
        return OutgoingMessage(text="❌ Отменено.", chat_id=message.chat_id)

    elif action == "correct":
        # Set conversation state to "correcting" so the next
        # message is treated as a category correction
        tx_id = parts[1] if len(parts) > 1 else None
        if tx_id:
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(UserContext).where(UserContext.user_id == uuid.UUID(context.user_id))
                    )
                    user_ctx = result.scalar_one_or_none()
                    if user_ctx:
                        user_ctx.conversation_state = ConversationState.correcting
                        user_ctx.last_transaction_id = uuid.UUID(tx_id)
                        await session.commit()
            except Exception as e:
                logger.error("Failed to set correcting state for user %s: %s", context.user_id, e)
        return OutgoingMessage(text="Введите правильную категорию:", chat_id=message.chat_id)

    elif action == "onboard":
        sub_action = parts[1] if len(parts) > 1 else "household"

        if sub_action == "new":
            # Owner flow: set state to awaiting_activity, ask for description
            await _set_onboarding_state(
                message.user_id, ConversationState.onboarding_awaiting_activity
            )
            return OutgoingMessage(
                text=(
                    "Расскажите о своей деятельности — чем занимаетесь?\n\n"
                    "Например: «я таксист», «у меня трак», "
                    "«просто хочу следить за расходами»"
                ),
                chat_id=message.chat_id,
            )

        elif sub_action == "join":
            # Family member flow: set state to awaiting_invite_code
            await _set_onboarding_state(
                message.user_id, ConversationState.onboarding_awaiting_invite_code
            )
            return OutgoingMessage(
                text="Введите код приглашения, который вам прислал владелец аккаунта:",
                chat_id=message.chat_id,
            )

        else:
            # Legacy: direct profile selection (e.g. onboard:trucker)
            profile_name = sub_action
            try:
                telegram_id = int(message.user_id)
                owner_name = context.user_id  # fallback
                async with async_session() as session:
                    family, user = await create_family(
                        session=session,
                        owner_telegram_id=telegram_id,
                        owner_name=owner_name,
                        business_type=profile_name if profile_name != "household" else None,
                        language=context.language,
                        currency=context.currency,
                    )
                logger.info(
                    "Onboarded user %s into family %s with profile '%s'",
                    user.id,
                    family.id,
                    profile_name,
                )
            except Exception as e:
                logger.error("Onboarding failed for user %s: %s", message.user_id, e)
                return OutgoingMessage(
                    text="Ошибка при настройке профиля. Попробуйте ещё раз.",
                    chat_id=message.chat_id,
                )
            return OutgoingMessage(
                text=f"Профиль «{profile_name}» настроен! Можете записывать расходы.",
                chat_id=message.chat_id,
            )

    elif action == "stats":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "weekly":
            # Redirect to query_stats with period=week
            registry = get_registry()
            skill = registry.get("query_stats")
            if skill:
                stats_message = IncomingMessage(
                    id=message.id,
                    user_id=message.user_id,
                    chat_id=message.chat_id,
                    type=MessageType.text,
                    text="статистика за неделю",
                )
                intent_data: dict[str, Any] = {"period": "week"}
                skill_result = await skill.execute(stats_message, context, intent_data)
                return OutgoingMessage(
                    text=skill_result.response_text,
                    chat_id=message.chat_id,
                    buttons=skill_result.buttons,
                    chart_url=skill_result.chart_url,
                )
        elif sub == "trend":
            # Show 3-month trend via query_stats
            registry = get_registry()
            skill = registry.get("query_stats")
            if skill:
                stats_message = IncomingMessage(
                    id=message.id,
                    user_id=message.user_id,
                    chat_id=message.chat_id,
                    type=MessageType.text,
                    text="тренд расходов за 3 месяца",
                )
                intent_data = {"period": "month"}
                skill_result = await skill.execute(stats_message, context, intent_data)
                return OutgoingMessage(
                    text=skill_result.response_text,
                    chat_id=message.chat_id,
                    buttons=skill_result.buttons,
                    chart_url=skill_result.chart_url,
                )
        return OutgoingMessage(text="Команда обработана.", chat_id=message.chat_id)

    elif action == "doc_save":
        # Retrieve full data from Redis: doc_save:<pending_id>
        pending_id = parts[1] if len(parts) > 1 else ""
        return await _save_scanned_document(pending_id, message, context)

    elif action == "receipt_confirm":
        # Create a Transaction from the receipt data
        merchant = parts[1] if len(parts) > 1 else "Unknown"
        total = Decimal(parts[2]) if len(parts) > 2 else Decimal("0")
        try:
            async with async_session() as session:
                # Pick the first available category for the family as default
                from src.core.models.category import Category

                cat_result = await session.execute(
                    select(Category)
                    .where(Category.family_id == uuid.UUID(context.family_id))
                    .limit(1)
                )
                category = cat_result.scalar_one_or_none()
                category_id = category.id if category else uuid.uuid4()

                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=category_id,
                    type=TransactionType.expense,
                    amount=total,
                    merchant=merchant,
                    description=f"Чек: {merchant}",
                    date=date.today(),
                    scope=Scope.family,
                    ai_confidence=Decimal("0.9"),
                    meta={"source": "receipt_scan"},
                )
                session.add(tx)
                await session.commit()
            logger.info(
                "Receipt transaction created: merchant=%s total=%s for user %s",
                merchant,
                total,
                context.user_id,
            )
        except Exception as e:
            logger.error("Failed to create receipt transaction: %s", e)
            return OutgoingMessage(
                text="Ошибка при записи чека. Попробуйте ещё раз.",
                chat_id=message.chat_id,
            )
        return OutgoingMessage(text="✅ Чек записан!", chat_id=message.chat_id)

    elif action == "receipt_cancel":
        # Also clean up any pending doc from Redis
        cancel_pending_id = parts[1] if len(parts) > 1 else ""
        if cancel_pending_id:
            from src.skills.scan_document.handler import delete_pending_doc

            await delete_pending_doc(cancel_pending_id)
        return OutgoingMessage(text="❌ Отменено.", chat_id=message.chat_id)

    return OutgoingMessage(text="Команда обработана.", chat_id=message.chat_id)


async def _save_scanned_document(
    pending_id: str,
    message: IncomingMessage,
    context: SessionContext,
) -> OutgoingMessage:
    """Save a scanned document from Redis pending data to DB.

    Creates Document record (with OCR data + image) and either
    a Transaction (receipt/invoice) or Load (rate_confirmation).
    """
    from src.skills.scan_document.handler import delete_pending_doc, get_pending_doc

    pending = await get_pending_doc(pending_id)
    if not pending:
        return OutgoingMessage(
            text="Данные документа истекли. Отправьте фото ещё раз.",
            chat_id=message.chat_id,
        )

    doc_type = pending["doc_type"]
    ocr_data = pending["ocr_data"]
    image_b64 = pending["image_b64"]
    mime_type = pending["mime_type"]
    fallback_used = pending["fallback_used"]

    ocr_model = "claude-haiku-4-5" if fallback_used else "gemini-3-flash-preview"

    DOC_TYPE_ENUM_MAP = {
        "receipt": DocumentType.receipt,
        "fuel_receipt": DocumentType.fuel_receipt,
        "invoice": DocumentType.invoice,
        "rate_confirmation": DocumentType.rate_confirmation,
        "other": DocumentType.other,
    }

    try:
        async with async_session() as session:
            from src.core.models.category import Category

            # 1. Create Document record with full OCR data + image
            doc = Document(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                type=DOC_TYPE_ENUM_MAP.get(doc_type, DocumentType.other),
                storage_path=f"inline:{mime_type}",
                ocr_model=ocr_model,
                ocr_raw={"image_b64": image_b64, "mime_type": mime_type},
                ocr_parsed=ocr_data,
                ocr_confidence=Decimal("0.9"),
                ocr_fallback_used=fallback_used,
            )
            session.add(doc)
            await session.flush()

            if doc_type == "rate_confirmation":
                # 2a. Save as Load record with all extracted fields
                pickup = None
                if ocr_data.get("pickup_date"):
                    try:
                        pickup = date.fromisoformat(ocr_data["pickup_date"])
                    except (ValueError, TypeError):
                        pickup = date.today()

                delivery = None
                if ocr_data.get("delivery_date"):
                    try:
                        delivery = date.fromisoformat(ocr_data["delivery_date"])
                    except (ValueError, TypeError):
                        pass

                load = Load(
                    family_id=uuid.UUID(context.family_id),
                    broker=ocr_data.get("broker", "Unknown"),
                    origin=ocr_data.get("origin", ""),
                    destination=ocr_data.get("destination", ""),
                    rate=Decimal(str(ocr_data.get("rate", 0))),
                    ref_number=ocr_data.get("ref_number"),
                    pickup_date=pickup or date.today(),
                    delivery_date=delivery,
                    status=LoadStatus.pending,
                    document_id=doc.id,
                )
                session.add(load)
                await session.commit()

                await delete_pending_doc(pending_id)
                broker = ocr_data.get("broker", "")
                rate_val = ocr_data.get("rate", 0)
                logger.info(
                    "Load saved: broker=%s rate=%s doc_id=%s user=%s",
                    broker, rate_val, doc.id, context.user_id,
                )
                return OutgoingMessage(
                    text=(
                        f"\u2705 Груз сохранён: {broker}, ${rate_val}\n"
                        f"\U0001f4c4 Документ ID: {doc.id}"
                    ),
                    chat_id=message.chat_id,
                )

            elif doc_type in ("receipt", "fuel_receipt", "invoice"):
                # 2b. Save as expense Transaction with full extracted data
                cat_result = await session.execute(
                    select(Category)
                    .where(Category.family_id == uuid.UUID(context.family_id))
                    .limit(1)
                )
                category = cat_result.scalar_one_or_none()
                category_id = category.id if category else uuid.uuid4()

                if doc_type == "invoice":
                    merchant = ocr_data.get("vendor", "Unknown")
                    amount = Decimal(str(ocr_data.get("total", 0)))
                    tx_date_str = ocr_data.get("date")
                    description = f"Invoice: {merchant}"
                    if ocr_data.get("invoice_number"):
                        description += f" #{ocr_data['invoice_number']}"
                else:
                    merchant = ocr_data.get("merchant", "Unknown")
                    amount = Decimal(str(ocr_data.get("total", 0)))
                    tx_date_str = ocr_data.get("date")
                    description = f"Receipt: {merchant}"

                tx_date = date.today()
                if tx_date_str:
                    try:
                        tx_date = date.fromisoformat(tx_date_str)
                    except (ValueError, TypeError):
                        pass

                meta = {"source": f"scan_{doc_type}"}
                if ocr_data.get("gallons"):
                    meta["gallons"] = ocr_data["gallons"]
                    meta["price_per_gallon"] = ocr_data.get("price_per_gallon")
                if ocr_data.get("items"):
                    meta["items"] = ocr_data["items"]
                if ocr_data.get("tax"):
                    meta["tax"] = str(ocr_data["tax"])

                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=category_id,
                    type=TransactionType.expense,
                    amount=amount,
                    merchant=merchant,
                    description=description,
                    date=tx_date,
                    scope=Scope.business if context.business_type else Scope.family,
                    state=ocr_data.get("state"),
                    document_id=doc.id,
                    ai_confidence=Decimal("0.9"),
                    meta=meta,
                )
                session.add(tx)
                await session.commit()

                await delete_pending_doc(pending_id)
                logger.info(
                    "Document saved: type=%s merchant=%s amount=%s doc_id=%s user=%s",
                    doc_type, merchant, amount, doc.id, context.user_id,
                )
                return OutgoingMessage(
                    text=(
                        f"\u2705 {doc_type.replace('_', ' ').capitalize()} "
                        f"сохранён: {merchant}, ${amount}\n"
                        f"\U0001f4c4 Документ ID: {doc.id}"
                    ),
                    chat_id=message.chat_id,
                )

            else:
                # 2c. Generic document — Document record only (no transaction)
                await session.commit()
                await delete_pending_doc(pending_id)
                logger.info("Generic document saved: doc_id=%s user=%s", doc.id, context.user_id)
                return OutgoingMessage(
                    text=f"\u2705 Документ сохранён\n\U0001f4c4 ID: {doc.id}",
                    chat_id=message.chat_id,
                )

    except Exception as e:
        logger.error("Failed to save scanned document: %s", e, exc_info=True)
        return OutgoingMessage(
            text="Ошибка при сохранении. Попробуйте ещё раз.",
            chat_id=message.chat_id,
        )
