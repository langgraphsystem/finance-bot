"""Scan receipt skill — OCR photo → structured data → INSERT."""

import json
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import anthropic_client, google_client
from src.core.models.document import Document
from src.core.models.enums import DocumentType, Scope, TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.schemas.receipt import ReceiptData
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

OCR_PROMPT = """Проанализируй фото чека и извлеки данные в JSON:
{
  "merchant": "название магазина/заправки",
  "total": число (итого),
  "date": "YYYY-MM-DD" или null,
  "items": [{"name": "товар", "quantity": 1, "price": 10.00}],
  "tax": число или null,
  "state": "штат" или null,
  "gallons": число или null (если топливо),
  "price_per_gallon": число или null
}
Ответь ТОЛЬКО валидным JSON."""


class ScanReceiptSkill:
    name = "scan_receipt"
    intents = ["scan_receipt"]
    model = "gemini-2.0-flash"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        if not message.photo_bytes and not message.photo_url:
            return SkillResult(response_text="Отправьте фото чека для распознавания.")

        # OCR with Gemini Flash (primary)
        try:
            receipt = await self._ocr_gemini(message)
        except Exception as e:
            logger.warning("Gemini OCR failed: %s, trying Claude fallback", e)
            try:
                receipt = await self._ocr_claude(message)
            except Exception as e2:
                logger.error("All OCR models failed: %s", e2)
                return SkillResult(
                    response_text="Не удалось распознать чек. Попробуйте сделать фото более чётким."
                )

        # Format response
        response = f"{receipt.merchant}, ${receipt.total}"
        if receipt.gallons:
            response += f"\n{receipt.gallons} gal @ ${receipt.price_per_gallon}"
        if receipt.state:
            response += f", {receipt.state}"

        # High-confidence result — auto-save to DB
        confidence = Decimal("0.9")
        if confidence > Decimal("0.95"):
            try:
                tx_id = await self._save_receipt_to_db(receipt, context)
                response += f"\n\nАвтоматически сохранено (ID: {tx_id})"
                return SkillResult(response_text=response)
            except Exception as e:
                logger.error("Auto-save receipt failed: %s", e)

        # Store pending receipt data for callback retrieval
        pending_id = str(uuid.uuid4())[:8]
        context_pending = getattr(context, "pending_confirmation", None)
        if context_pending is None:
            context.pending_confirmation = {}  # type: ignore[attr-defined]
        context.pending_confirmation[pending_id] = receipt  # type: ignore[attr-defined]

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "\u2705 Верно", "callback": f"receipt_confirm:{pending_id}"},
                {"text": "\u270f\ufe0f Категория", "callback": f"receipt_correct:{pending_id}"},
                {"text": "\U0001f4b0 Сумма", "callback": f"receipt_amount:{pending_id}"},
                {"text": "\u274c Отмена", "callback": "receipt_cancel"},
            ],
        )

    async def _save_receipt_to_db(self, receipt: ReceiptData, context: SessionContext) -> str:
        """Save receipt as Transaction + Document. Returns transaction ID."""
        async with async_session() as session:
            # 1. Create Document record
            doc = Document(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                type=DocumentType.receipt,
                storage_path="pending",  # TODO: Supabase upload
                ocr_model="gemini-2.0-flash",
                ocr_parsed=receipt.model_dump(mode="json"),
                ocr_confidence=Decimal("0.9"),
            )
            session.add(doc)
            await session.flush()

            # 2. Resolve category from merchant mappings
            category_id = self._resolve_category(receipt.merchant, context)

            # 3. Create Transaction
            tx = Transaction(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                category_id=(
                    uuid.UUID(category_id)
                    if category_id
                    else uuid.UUID(context.categories[0]["id"])
                ),
                type=TransactionType.expense,
                amount=receipt.total,
                merchant=receipt.merchant,
                date=date.fromisoformat(receipt.date) if receipt.date else date.today(),
                scope=Scope.business if context.business_type else Scope.family,
                state=receipt.state,
                meta=(
                    {
                        "gallons": receipt.gallons,
                        "price_per_gallon": float(
                            receipt.price_per_gallon,
                        ),
                    }
                    if receipt.gallons
                    else None
                ),
                document_id=doc.id,
                ai_confidence=Decimal("0.9"),
            )
            session.add(tx)
            await session.commit()
            return str(tx.id)

    def _resolve_category(self, merchant: str, context: SessionContext) -> str | None:
        """Resolve category ID from merchant_mappings in context."""
        if not merchant or not context.merchant_mappings:
            return None
        merchant_lower = merchant.lower()
        for mapping in context.merchant_mappings:
            pattern = mapping.get("merchant", "").lower()
            if pattern and pattern in merchant_lower:
                return mapping.get("category_id")
        return None

    @observe(name="ocr_gemini")
    async def _ocr_gemini(self, message: IncomingMessage) -> ReceiptData:
        client = google_client()

        parts = [OCR_PROMPT]
        if message.photo_bytes:
            import base64

            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(message.photo_bytes).decode(),
                    }
                }
            )

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=parts,
            config={"response_mime_type": "application/json"},
        )
        data = json.loads(response.text)
        return ReceiptData(**data)

    @observe(name="ocr_claude")
    async def _ocr_claude(self, message: IncomingMessage) -> ReceiptData:
        client = anthropic_client()

        content = [{"type": "text", "text": OCR_PROMPT}]
        if message.photo_bytes:
            import base64

            content.insert(
                0,
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(message.photo_bytes).decode(),
                    },
                },
            )

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        return ReceiptData(**data)

    def get_system_prompt(self, context: SessionContext) -> str:
        return OCR_PROMPT


skill = ScanReceiptSkill()
