"""Universal document scanner — classifies and extracts data from any photo/document."""

import base64
import json
import logging
import uuid
from typing import Any

from src.core.context import SessionContext
from src.core.db import redis
from src.core.llm.clients import anthropic_client, google_client
from src.core.observability import observe
from src.core.schemas.document_scan import GenericDocumentData, InvoiceData
from src.core.schemas.load import LoadData
from src.core.schemas.receipt import ReceiptData
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

PENDING_DOC_TTL = 3600  # 1 hour

CLASSIFY_PROMPT = """Определи тип документа на фото. Ответь ТОЛЬКО одним словом:
- receipt (чек, кассовый чек, товарный чек)
- invoice (счёт, инвойс, счёт-фактура, bill)
- rate_confirmation (rate confirmation, подтверждение рейса, load confirmation)
- fuel_receipt (заправочный чек, топливо, gas receipt)
- other (всё остальное: договор, документ, картинка, скриншот, текст)

Ответ (одно слово):"""

RECEIPT_OCR_PROMPT = """Проанализируй фото чека и извлеки данные в JSON:
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

INVOICE_OCR_PROMPT = """Проанализируй фото инвойса/счёта и извлеки данные в JSON:
{
  "vendor": "название компании-поставщика",
  "invoice_number": "номер инвойса" или null,
  "date": "YYYY-MM-DD" или null,
  "due_date": "YYYY-MM-DD" или null,
  "total": число (итого к оплате),
  "subtotal": число или null,
  "tax": число или null,
  "currency": "USD" или другая валюта,
  "items": [{"description": "описание", "quantity": 1, "unit_price": 100, "total": 100}],
  "notes": "примечания" или null
}
Ответь ТОЛЬКО валидным JSON."""

RATE_CONF_OCR_PROMPT = """Проанализируй фото rate confirmation и извлеки данные в JSON:
{
  "broker": "название брокера/компании",
  "origin": "город/штат отправления",
  "destination": "город/штат назначения",
  "rate": число (ставка за рейс),
  "ref_number": "номер рейса/reference" или null,
  "pickup_date": "YYYY-MM-DD" или null,
  "delivery_date": "YYYY-MM-DD" или null
}
Ответь ТОЛЬКО валидным JSON."""

GENERIC_OCR_PROMPT = """Проанализируй фото/документ и извлеки информацию в JSON:
{
  "title": "заголовок/тема документа" или null,
  "doc_type": "тип документа (договор, справка, скриншот, и т.д.)",
  "extracted_text": "основной текст документа",
  "key_values": {"ключ": "значение"},
  "dates": ["YYYY-MM-DD"],
  "amounts": ["$100.00"],
  "summary": "краткое описание документа (1-2 предложения)"
}
Ответь ТОЛЬКО валидным JSON."""

PROMPT_MAP = {
    "receipt": RECEIPT_OCR_PROMPT,
    "fuel_receipt": RECEIPT_OCR_PROMPT,
    "invoice": INVOICE_OCR_PROMPT,
    "rate_confirmation": RATE_CONF_OCR_PROMPT,
    "other": GENERIC_OCR_PROMPT,
}


async def store_pending_doc(
    pending_id: str,
    doc_type: str,
    ocr_data: dict,
    image_bytes: bytes,
    mime_type: str,
    fallback_used: bool,
    user_id: str,
    family_id: str,
) -> None:
    """Store pending document data in Redis for later save on user confirm."""
    payload = {
        "doc_type": doc_type,
        "ocr_data": ocr_data,
        "image_b64": base64.b64encode(image_bytes).decode(),
        "mime_type": mime_type,
        "fallback_used": fallback_used,
        "user_id": user_id,
        "family_id": family_id,
    }
    key = f"pending_doc:{pending_id}"
    await redis.set(key, json.dumps(payload, default=str), ex=PENDING_DOC_TTL)


async def get_pending_doc(pending_id: str) -> dict | None:
    """Retrieve pending document data from Redis."""
    key = f"pending_doc:{pending_id}"
    data = await redis.get(key)
    if not data:
        return None
    return json.loads(data)


async def delete_pending_doc(pending_id: str) -> None:
    """Delete pending document data from Redis."""
    await redis.delete(f"pending_doc:{pending_id}")


class ScanDocumentSkill:
    name = "scan_document"
    intents = ["scan_document", "scan_receipt"]
    model = "gemini-3-flash-preview"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        image_bytes = message.photo_bytes or message.document_bytes
        if not image_bytes:
            return SkillResult(response_text="Отправьте фото или документ для распознавания.")

        mime_type = message.document_mime_type or "image/jpeg"
        fallback_used = False

        # Step 1: Classify document type
        try:
            doc_type = await self._classify(image_bytes, mime_type)
        except Exception as e:
            logger.warning("Document classification failed: %s, defaulting to 'other'", e)
            doc_type = "other"

        # Step 2: Extract data based on type
        try:
            raw_data = await self._extract(image_bytes, mime_type, doc_type)
        except Exception as e:
            logger.warning("Gemini extraction failed: %s, trying Claude fallback", e)
            try:
                raw_data = await self._extract_claude(image_bytes, mime_type, doc_type)
                fallback_used = True
            except Exception as e2:
                logger.error("All OCR models failed: %s", e2)
                return SkillResult(
                    response_text="Не удалось распознать документ. "
                    "Попробуйте сделать фото более чётким."
                )

        # Step 3: Store pending data in Redis for later save
        pending_id = str(uuid.uuid4())[:8]
        await store_pending_doc(
            pending_id=pending_id,
            doc_type=doc_type,
            ocr_data=raw_data,
            image_bytes=image_bytes,
            mime_type=mime_type,
            fallback_used=fallback_used,
            user_id=context.user_id,
            family_id=context.family_id,
        )

        # Step 4: Format response based on document type
        if doc_type in ("receipt", "fuel_receipt"):
            return self._format_receipt(raw_data, doc_type, pending_id)
        elif doc_type == "invoice":
            return self._format_invoice(raw_data, pending_id)
        elif doc_type == "rate_confirmation":
            return self._format_rate_conf(raw_data, pending_id)
        else:
            return self._format_generic(raw_data, pending_id)

    @observe(name="doc_classify")
    async def _classify(self, image_bytes: bytes, mime_type: str) -> str:
        """Classify document type using Gemini 3 Flash."""
        client = google_client()
        parts = [
            CLASSIFY_PROMPT,
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode(),
                }
            },
        ]
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=parts,
        )
        result = response.text.strip().lower()
        for valid_type in ("receipt", "invoice", "rate_confirmation", "fuel_receipt", "other"):
            if valid_type in result:
                return valid_type
        return "other"

    @observe(name="doc_extract_gemini")
    async def _extract(self, image_bytes: bytes, mime_type: str, doc_type: str) -> dict:
        """Extract structured data using Gemini 3 Flash."""
        client = google_client()
        prompt = PROMPT_MAP.get(doc_type, GENERIC_OCR_PROMPT)
        parts = [
            prompt,
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode(),
                }
            },
        ]
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=parts,
            config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    @observe(name="doc_extract_claude")
    async def _extract_claude(self, image_bytes: bytes, mime_type: str, doc_type: str) -> dict:
        """Fallback extraction using Claude Haiku."""
        client = anthropic_client()
        prompt = PROMPT_MAP.get(doc_type, GENERIC_OCR_PROMPT)
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode(),
                },
            },
            {"type": "text", "text": prompt},
        ]
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])

    def _format_receipt(self, data: dict, doc_type: str, pending_id: str) -> SkillResult:
        """Format receipt/fuel receipt response."""
        try:
            receipt = ReceiptData(**data)
        except Exception:
            return self._format_generic(data, pending_id)

        is_fuel = doc_type == "fuel_receipt" or receipt.gallons
        icon = "\u26fd" if is_fuel else "\U0001f9fe"
        label = "Заправочный чек" if is_fuel else "Чек"

        response = f"{icon} <b>{label} распознан</b>\n\n"
        response += f"\U0001f3ea <b>Магазин:</b> {receipt.merchant}\n"
        response += f"\U0001f4b5 <b>Сумма:</b> ${receipt.total}"
        if receipt.tax:
            response += f" (налог: ${receipt.tax})"
        response += "\n"
        if receipt.date:
            response += f"\U0001f4c5 <b>Дата:</b> {receipt.date}\n"
        if receipt.gallons:
            response += (
                f"\u26fd <b>Топливо:</b> {receipt.gallons} gal @ ${receipt.price_per_gallon}/gal\n"
            )
        if receipt.state:
            response += f"\U0001f4cd <b>Штат:</b> {receipt.state}\n"
        if receipt.items:
            response += "\n\U0001f4cb <b>Товары:</b>\n"
            for item in receipt.items[:10]:
                name = item.name if hasattr(item, "name") else item.get("name", "\u2014")
                qty = item.quantity if hasattr(item, "quantity") else item.get("quantity", 1)
                price = item.price if hasattr(item, "price") else item.get("price", 0)
                line = f"  \u2022 {name}"
                if qty and qty > 1:
                    line += f" \u00d7{qty}"
                if price:
                    line += f" \u2014 ${price}"
                response += line + "\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "\u2705 Сохранить", "callback": f"doc_save:{pending_id}"},
                {"text": "\u270f\ufe0f Категория", "callback": f"receipt_correct:{pending_id}"},
                {"text": "\u274c Отмена", "callback": "receipt_cancel"},
            ],
        )

    def _format_invoice(self, data: dict, pending_id: str) -> SkillResult:
        """Format invoice response."""
        try:
            invoice = InvoiceData(**data)
        except Exception:
            return self._format_generic(data, pending_id)

        response = "\U0001f4c4 <b>Инвойс распознан</b>\n\n"
        response += f"\U0001f3e2 <b>Поставщик:</b> {invoice.vendor}\n"
        if invoice.invoice_number:
            response += f"\U0001f522 <b>Номер:</b> {invoice.invoice_number}\n"
        response += f"\U0001f4b5 <b>Сумма:</b> ${invoice.total}"
        if invoice.currency and invoice.currency != "USD":
            response += f" {invoice.currency}"
        response += "\n"
        if invoice.subtotal:
            response += f"   Подитог: ${invoice.subtotal}\n"
        if invoice.tax:
            response += f"   Налог: ${invoice.tax}\n"
        if invoice.date:
            response += f"\U0001f4c5 <b>Дата:</b> {invoice.date}\n"
        if invoice.due_date:
            response += f"\u23f0 <b>Срок оплаты:</b> {invoice.due_date}\n"
        if invoice.items:
            response += "\n\U0001f4cb <b>Позиции:</b>\n"
            for item in invoice.items[:10]:
                desc = item.get("description", "\u2014")
                total = item.get("total", "")
                line = f"  \u2022 {desc}"
                if total:
                    line += f" \u2014 ${total}"
                response += line + "\n"
        if invoice.notes:
            response += f"\n\U0001f4dd <b>Примечания:</b> {invoice.notes}\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "\u2705 Сохранить как расход", "callback": f"doc_save:{pending_id}"},
                {"text": "\u274c Отмена", "callback": "receipt_cancel"},
            ],
        )

    def _format_rate_conf(self, data: dict, pending_id: str) -> SkillResult:
        """Format rate confirmation response."""
        try:
            load = LoadData(**data)
        except Exception:
            return self._format_generic(data, pending_id)

        response = "\U0001f69a <b>Rate Confirmation распознан</b>\n\n"
        response += f"\U0001f3e2 <b>Брокер:</b> {load.broker}\n"
        response += f"\U0001f4b0 <b>Ставка:</b> ${load.rate}\n"
        if load.ref_number:
            response += f"\U0001f522 <b>Ref #:</b> {load.ref_number}\n"
        response += f"\U0001f4cd <b>Откуда:</b> {load.origin}\n"
        response += f"\U0001f3c1 <b>Куда:</b> {load.destination}\n"
        if load.pickup_date:
            response += f"\U0001f4c5 <b>Пикап:</b> {load.pickup_date}\n"
        if load.delivery_date:
            response += f"\U0001f4e6 <b>Доставка:</b> {load.delivery_date}\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "\u2705 Сохранить груз", "callback": f"doc_save:{pending_id}"},
                {"text": "\u274c Отмена", "callback": "receipt_cancel"},
            ],
        )

    def _format_generic(self, data: dict, pending_id: str) -> SkillResult:
        """Format generic document/image response."""
        try:
            doc = GenericDocumentData(**data)
        except Exception:
            doc = GenericDocumentData(
                summary=str(data)[:500],
                extracted_text=json.dumps(data, ensure_ascii=False)[:1000],
            )

        response = "\U0001f4c4 <b>Документ распознан</b>\n\n"
        if doc.title:
            response += f"\U0001f4cc <b>Заголовок:</b> {doc.title}\n"
        if doc.doc_type:
            response += f"\U0001f4c1 <b>Тип:</b> {doc.doc_type}\n"
        if doc.summary:
            response += f"\n\U0001f4dd <b>Описание:</b>\n{doc.summary}\n"
        if doc.key_values:
            response += "\n\U0001f511 <b>Ключевые данные:</b>\n"
            for k, v in list(doc.key_values.items())[:10]:
                response += f"  \u2022 {k}: {v}\n"
        if doc.amounts:
            response += "\n\U0001f4b0 <b>Суммы:</b> " + ", ".join(doc.amounts[:5]) + "\n"
        if doc.dates:
            response += "\U0001f4c5 <b>Даты:</b> " + ", ".join(doc.dates[:5]) + "\n"
        if doc.extracted_text and not doc.summary:
            text_preview = doc.extracted_text[:300]
            if len(doc.extracted_text) > 300:
                text_preview += "..."
            response += f"\n<b>Текст:</b>\n<code>{text_preview}</code>\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "\u2705 Сохранить", "callback": f"doc_save:{pending_id}"},
                {"text": "\u274c Отмена", "callback": "receipt_cancel"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CLASSIFY_PROMPT


skill = ScanDocumentSkill()
