"""Telegram Gateway — aiogram v3 implementation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.types import BufferedInputFile
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _AIOGRAM_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency in CI
    Bot = Dispatcher = types = None  # type: ignore[assignment]
    BufferedInputFile = None  # type: ignore[assignment]
    InlineKeyboardBuilder = None  # type: ignore[assignment]
    _AIOGRAM_AVAILABLE = False

from src.core.formatting import md_to_telegram_html
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)


class _NoopDispatcher:
    def message(self):
        def decorator(func):  # noqa: ANN001, ANN202
            return func

        return decorator

    def callback_query(self):
        def decorator(func):  # noqa: ANN001, ANN202
            return func

        return decorator

    async def feed_update(self, bot, update) -> None:  # noqa: ANN001, ARG002
        raise RuntimeError("aiogram is not installed")


def _require_aiogram(operation: str) -> None:
    if _AIOGRAM_AVAILABLE:
        return
    raise RuntimeError(
        "Telegram gateway requires aiogram "
        f"(operation: {operation}). Install aiogram."
    )


class TelegramGateway:
    """Gateway implementation for Telegram via aiogram v3."""

    def __init__(self, token: str, webhook_url: str = ""):
        self.bot = Bot(token=token) if _AIOGRAM_AVAILABLE else None
        self.dp = Dispatcher() if _AIOGRAM_AVAILABLE else _NoopDispatcher()
        self.webhook_url = webhook_url
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

    def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]) -> None:
        self._handler = handler

        @self.dp.message()
        async def _on_message(msg: types.Message):
            incoming = await self._convert_message(msg)
            await self._handler(incoming)

        @self.dp.callback_query()
        async def _on_callback(callback: types.CallbackQuery):
            incoming = IncomingMessage(
                id=str(callback.id),
                user_id=str(callback.from_user.id),
                chat_id=str(callback.message.chat.id),
                type=MessageType.callback,
                callback_data=callback.data,
                language=callback.from_user.language_code if callback.from_user else None,
                raw=callback,
            )
            await self._handler(incoming)
            if callback.data and callback.data.startswith("sched:") and callback.message:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception as e:
                    logger.debug("Failed to clear sched callback buttons: %s", e)
            await callback.answer()

    async def send(self, message: OutgoingMessage) -> None:
        if self.bot is None:
            _require_aiogram("send")

        reply_markup = None
        if message.reply_keyboard:
            from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

            kb_buttons = [
                KeyboardButton(
                    text=btn["text"],
                    request_location=btn.get("request_location", False),
                    request_contact=btn.get("request_contact", False),
                )
                for btn in message.reply_keyboard
            ]
            reply_markup = ReplyKeyboardMarkup(
                keyboard=[kb_buttons], resize_keyboard=True, one_time_keyboard=True
            )
        elif message.remove_reply_keyboard:
            from aiogram.types import ReplyKeyboardRemove

            reply_markup = ReplyKeyboardRemove()
        elif message.buttons:
            builder = InlineKeyboardBuilder()
            for btn in message.buttons:
                if "url" in btn:
                    builder.button(text=btn["text"], url=btn["url"])
                elif "callback" in btn:
                    builder.button(text=btn["text"], callback_data=btn["callback"])
            builder.adjust(2)
            reply_markup = builder.as_markup()

        # Convert LLM Markdown to Telegram HTML
        if message.parse_mode == "HTML" and message.text:
            message.text = md_to_telegram_html(message.text)

        kwargs = {"chat_id": int(message.chat_id), "parse_mode": message.parse_mode}

        if message.document:
            file = BufferedInputFile(message.document, filename=message.document_name or "file")
            await self.bot.send_document(
                **kwargs, document=file, caption=message.text, reply_markup=reply_markup
            )
        elif message.photo_bytes:
            file = BufferedInputFile(message.photo_bytes, filename="card.png")
            await self.bot.send_photo(
                **kwargs, photo=file, caption=message.text, reply_markup=reply_markup
            )
        elif message.chart_url or message.photo_url:
            photo = message.chart_url or message.photo_url
            await self.bot.send_photo(
                **kwargs, photo=photo, caption=message.text, reply_markup=reply_markup
            )
        else:
            text = message.text or ""
            if len(text) > 4000:
                chunks = _split_message(text, max_len=4000)
                for i, chunk in enumerate(chunks):
                    rm = reply_markup if i == len(chunks) - 1 else None
                    await self.bot.send_message(**kwargs, text=chunk, reply_markup=rm)
            else:
                await self.bot.send_message(
                    **kwargs, text=text, reply_markup=reply_markup
                )

    async def send_typing(self, chat_id: str) -> None:
        if self.bot is None:
            _require_aiogram("send_typing")
        await self.bot.send_chat_action(chat_id=int(chat_id), action="typing")

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        """Delete a message from chat (used for password security)."""
        if self.bot is None:
            _require_aiogram("delete_message")
        try:
            await self.bot.delete_message(
                chat_id=int(chat_id), message_id=int(message_id)
            )
        except Exception as e:
            logger.warning("Failed to delete message %s: %s", message_id, e)

    async def start(self) -> None:
        if self.bot is None:
            _require_aiogram("start")
        if self.webhook_url:
            # Delete+set to force Telegram to re-resolve DNS/IP after deploy
            await self.bot.delete_webhook()
            await self.bot.set_webhook(self.webhook_url)
            logger.info("Webhook set to %s", self.webhook_url)
        else:
            logger.info("No webhook URL, use feed_update() for webhook mode")

    async def stop(self) -> None:
        if self.bot is None:
            _require_aiogram("stop")
        await self.bot.delete_webhook()
        await self.bot.session.close()

    async def feed_update(self, data: dict) -> None:
        """Feed a raw webhook update to aiogram dispatcher."""
        if self.bot is None:
            _require_aiogram("feed_update")
        update = types.Update(**data)
        await self.dp.feed_update(self.bot, update)

    async def _convert_message(self, msg: types.Message) -> IncomingMessage:
        """Convert aiogram Message to IncomingMessage."""
        if self.bot is None:
            _require_aiogram("convert_message")
        msg_type = MessageType.text
        photo_bytes: bytes | None = None
        voice_bytes: bytes | None = None

        if msg.photo:
            msg_type = MessageType.photo
            try:
                photo = msg.photo[-1]  # largest resolution
                file = await self.bot.get_file(photo.file_id)
                data = await self.bot.download_file(file.file_path)
                photo_bytes = data.read()
            except Exception as e:
                logger.error("Failed to download photo from Telegram: %s", e)
        elif msg.voice:
            msg_type = MessageType.voice
            try:
                file = await self.bot.get_file(msg.voice.file_id)
                data = await self.bot.download_file(file.file_path)
                voice_bytes = data.read()
            except Exception as e:
                logger.error("Failed to download voice from Telegram: %s", e)
        elif msg.location:
            return IncomingMessage(
                id=str(msg.message_id),
                user_id=str(msg.from_user.id),
                chat_id=str(msg.chat.id),
                type=MessageType.location,
                text=f"{msg.location.latitude},{msg.location.longitude}",
                language=msg.from_user.language_code if msg.from_user else None,
                raw=msg,
            )
        elif msg.document:
            msg_type = MessageType.document
            document_bytes = None
            document_mime_type = msg.document.mime_type
            document_file_name = msg.document.file_name
            # Download documents that are images or PDFs (up to 20MB Telegram limit)
            try:
                file = await self.bot.get_file(msg.document.file_id)
                data = await self.bot.download_file(file.file_path)
                document_bytes = data.read()
            except Exception as e:
                logger.error("Failed to download document from Telegram: %s", e)

            return IncomingMessage(
                id=str(msg.message_id),
                user_id=str(msg.from_user.id),
                chat_id=str(msg.chat.id),
                type=msg_type,
                text=msg.text or msg.caption,
                document_bytes=document_bytes,
                document_mime_type=document_mime_type,
                document_file_name=document_file_name,
                language=msg.from_user.language_code if msg.from_user else None,
                raw=msg,
            )

        return IncomingMessage(
            id=str(msg.message_id),
            user_id=str(msg.from_user.id),
            chat_id=str(msg.chat.id),
            type=msg_type,
            text=msg.text or msg.caption,
            photo_bytes=photo_bytes,
            voice_bytes=voice_bytes,
            language=msg.from_user.language_code if msg.from_user else None,
            raw=msg,
        )


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks that fit Telegram's 4096-char limit.

    Splits on paragraph boundaries first, then newlines, then hard-cuts.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut > max_len // 3:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 2:]
            continue

        # Try to split at newline
        cut = remaining.rfind("\n", 0, max_len)
        if cut > max_len // 3:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1:]
            continue

        # Hard cut at max_len
        chunks.append(remaining[:max_len])
        remaining = remaining[max_len:]

    return chunks
