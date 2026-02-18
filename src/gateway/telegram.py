"""Telegram Gateway — aiogram v3 implementation."""

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.core.formatting import md_to_telegram_html
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

logger = logging.getLogger(__name__)


class TelegramGateway:
    """Gateway implementation for Telegram via aiogram v3."""

    def __init__(self, token: str, webhook_url: str = ""):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
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
                raw=callback,
            )
            await self._handler(incoming)
            await callback.answer()

    async def send(self, message: OutgoingMessage) -> None:
        reply_markup = None
        if message.buttons:
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
        elif message.chart_url or message.photo_url:
            photo = message.chart_url or message.photo_url
            await self.bot.send_photo(
                **kwargs, photo=photo, caption=message.text, reply_markup=reply_markup
            )
        else:
            await self.bot.send_message(**kwargs, text=message.text, reply_markup=reply_markup)

    async def send_typing(self, chat_id: str) -> None:
        await self.bot.send_chat_action(chat_id=int(chat_id), action="typing")

    async def start(self) -> None:
        if self.webhook_url:
            await self.bot.set_webhook(self.webhook_url)
            logger.info("Webhook set to %s", self.webhook_url)
        else:
            logger.info("No webhook URL, use feed_update() for webhook mode")

    async def stop(self) -> None:
        await self.bot.delete_webhook()
        await self.bot.session.close()

    async def feed_update(self, data: dict) -> None:
        """Feed a raw webhook update to aiogram dispatcher."""
        update = types.Update(**data)
        await self.dp.feed_update(self.bot, update)

    async def _convert_message(self, msg: types.Message) -> IncomingMessage:
        """Convert aiogram Message to IncomingMessage."""
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
            raw=msg,
        )
