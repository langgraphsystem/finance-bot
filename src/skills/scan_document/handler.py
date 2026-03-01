"""Universal document scanner — classifies and extracts data from any photo/document."""

import base64
import json
import logging
import uuid
from typing import Any

import instructor
from pydantic import BaseModel

from src.core.context import SessionContext
from src.core.db import redis
from src.core.llm.clients import anthropic_client, google_client
from src.core.observability import observe
from src.core.schemas.document_scan import GenericDocumentData, InvoiceData
from src.core.schemas.load import LoadData
from src.core.schemas.receipt import ReceiptData
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.tools.document_reader import extract_pages_as_images

logger = logging.getLogger(__name__)


def _t(lang: str | None, en: str, ru: str, es: str = "") -> str:
    if lang == "ru":
        return ru
    if lang == "es":
        return es or en
    return en


PENDING_DOC_TTL = 3600  # 1 hour

# Maximum pages to send to the LLM in a single request (avoids context overflow)
MAX_PDF_PAGES = 10

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

# Maps doc_type to the Pydantic model used for Instructor structured extraction
SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "receipt": ReceiptData,
    "fuel_receipt": ReceiptData,
    "invoice": InvoiceData,
    "rate_confirmation": LoadData,
    "other": GenericDocumentData,
}


def _is_pdf(mime_type: str | None, filename: str | None) -> bool:
    """Return True if the document is a PDF."""
    if mime_type and "pdf" in mime_type.lower():
        return True
    if filename and filename.lower().endswith(".pdf"):
        return True
    return False


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
    intents = ["scan_document"]
    model = "gemini-3-flash-preview"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        image_bytes = message.photo_bytes or message.document_bytes
        lang = context.language or "en"
        if not image_bytes:
            return SkillResult(
                response_text=_t(
                    lang,
                    "Send a photo or document to scan.",
                    "Отправьте фото или документ для распознавания.",
                    "Envie una foto o documento para escanear.",
                )
            )

        mime_type = message.document_mime_type or "image/jpeg"
        filename = message.document_file_name or ""
        fallback_used = False

        # --- Multi-page PDF handling ---
        # Extract all pages as PNG images when the input is a PDF.
        # The page images are used for both classification and OCR so the LLM
        # sees the full document rather than only the first page.
        pdf_page_images: list[bytes] = []
        if _is_pdf(mime_type, filename):
            try:
                all_pages = await extract_pages_as_images(image_bytes, filename or "doc.pdf")
                if all_pages:
                    pdf_page_images = all_pages[:MAX_PDF_PAGES]
                    logger.info(
                        "PDF split into %d page(s) (total %d)",
                        len(pdf_page_images),
                        len(all_pages),
                    )
            except Exception as e:
                logger.warning("PDF page extraction failed: %s, falling back to raw bytes", e)

        # Step 1: Classify document type
        # Use first page image for classification (covers the document header).
        classify_bytes = pdf_page_images[0] if pdf_page_images else image_bytes
        classify_mime = "image/png" if pdf_page_images else mime_type
        try:
            doc_type = await self._classify(classify_bytes, classify_mime)
        except Exception as e:
            logger.warning("Document classification failed: %s, defaulting to 'other'", e)
            doc_type = "other"

        # Step 2: Extract data — pass all PDF pages in one request when available
        try:
            raw_data = await self._extract(
                image_bytes=image_bytes,
                mime_type=mime_type,
                doc_type=doc_type,
                pdf_pages=pdf_page_images,
            )
        except Exception as e:
            logger.warning("Gemini extraction failed: %s, trying Claude fallback", e)
            try:
                raw_data = await self._extract_claude(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    doc_type=doc_type,
                    pdf_pages=pdf_page_images,
                )
                fallback_used = True
            except Exception as e2:
                logger.error("All OCR models failed: %s", e2)
                return SkillResult(
                    response_text=_t(
                        lang,
                        "Failed to recognize the document. Try a clearer photo.",
                        "Не удалось распознать документ. Попробуйте сделать фото более чётким.",
                        "No se pudo reconocer el documento. Intente con una foto mas clara.",
                    )
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
            return self._format_receipt(raw_data, doc_type, pending_id, lang)
        elif doc_type == "invoice":
            return self._format_invoice(raw_data, pending_id, lang)
        elif doc_type == "rate_confirmation":
            return self._format_rate_conf(raw_data, pending_id, lang)
        else:
            return self._format_generic(raw_data, pending_id, lang)

    @observe(name="doc_classify")
    async def _classify(self, image_bytes: bytes, mime_type: str) -> str:
        """Classify document type using Gemini 3 Flash (first page image)."""
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
    async def _extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        doc_type: str,
        pdf_pages: list[bytes],
    ) -> dict:
        """Extract structured data using Gemini 3 Flash.

        When ``pdf_pages`` is provided, all page images are sent in a single
        request so multi-page documents (e.g. multi-page invoices) are processed
        in full rather than just the first page.
        """
        client = google_client()
        prompt = PROMPT_MAP.get(doc_type, GENERIC_OCR_PROMPT)

        if pdf_pages:
            # Build a multi-image request: one inline_data block per PDF page
            parts: list = [prompt]
            for page_bytes in pdf_pages:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(page_bytes).decode(),
                        }
                    }
                )
        else:
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
    async def _extract_claude(
        self,
        image_bytes: bytes,
        mime_type: str,
        doc_type: str,
        pdf_pages: list[bytes],
    ) -> dict:
        """Fallback extraction using Claude Sonnet via Instructor for typed output.

        When ``pdf_pages`` is provided, all page images are included in a single
        request.  The Instructor library handles structured extraction and
        validates the response against the appropriate Pydantic model, so manual
        JSON slicing is no longer required.
        """
        response_model: type[BaseModel] = SCHEMA_MAP.get(doc_type, GenericDocumentData)
        prompt = PROMPT_MAP.get(doc_type, GENERIC_OCR_PROMPT)

        # Build the content blocks: images first, then the text prompt
        content: list[dict] = []

        if pdf_pages:
            for page_bytes in pdf_pages:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(page_bytes).decode(),
                        },
                    }
                )
        else:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode(),
                    },
                }
            )

        content.append({"type": "text", "text": prompt})

        # Instructor wraps AsyncAnthropic and returns a validated Pydantic instance
        ic = instructor.from_anthropic(anthropic_client())
        result: BaseModel = await ic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
            response_model=response_model,
        )
        return result.model_dump(mode="json")

    def _format_receipt(
        self, data: dict, doc_type: str, pending_id: str, lang: str = "en"
    ) -> SkillResult:
        """Format receipt/fuel receipt response."""
        try:
            receipt = ReceiptData(**data)
        except Exception:
            return self._format_generic(data, pending_id, lang)

        is_fuel = doc_type == "fuel_receipt" or receipt.gallons
        icon = "\u26fd" if is_fuel else "\U0001f9fe"
        label = _t(
            lang,
            "Fuel receipt" if is_fuel else "Receipt",
            "Заправочный чек" if is_fuel else "Чек",
            "Recibo de combustible" if is_fuel else "Recibo",
        )

        response = (
            f"{icon} <b>{label} " + _t(lang, "recognized", "распознан", "reconocido") + "</b>\n\n"
        )
        response += (
            f"\U0001f3ea <b>{_t(lang, 'Store:', 'Магазин:', 'Tienda:')}</b> {receipt.merchant}\n"
        )
        response += f"\U0001f4b5 <b>{_t(lang, 'Amount:', 'Сумма:', 'Monto:')}</b> ${receipt.total}"
        if receipt.tax:
            response += f" ({_t(lang, 'tax', 'налог', 'impuesto')}: ${receipt.tax})"
        response += "\n"
        if receipt.date:
            response += f"\U0001f4c5 <b>{_t(lang, 'Date:', 'Дата:', 'Fecha:')}</b> {receipt.date}\n"
        if receipt.gallons:
            fuel_lbl = _t(lang, "Fuel:", "Топливо:", "Combustible:")
            response += (
                f"\u26fd <b>{fuel_lbl}</b> {receipt.gallons} gal"
                f" @ ${receipt.price_per_gallon}/gal\n"
            )
        if receipt.state:
            response += (
                f"\U0001f4cd <b>{_t(lang, 'State:', 'Штат:', 'Estado:')}</b> {receipt.state}\n"
            )
        if receipt.items and not is_fuel:
            response += f"\n\U0001f4cb <b>{_t(lang, 'Items:', 'Товары:', 'Articulos:')}</b>\n"
            for item in receipt.items[:10]:
                name = item.name if hasattr(item, "name") else item.get("name", "\u2014")
                qty = item.quantity if hasattr(item, "quantity") else item.get("quantity", 1)
                price = item.price if hasattr(item, "price") else item.get("price", 0)
                line = f"  \u2022 {name}"
                if qty and float(qty) != 1:
                    total_price = float(price) * float(qty)
                    line += f" \u00d7{qty} \u2014 ${total_price:.2f}"
                elif price:
                    line += f" \u2014 ${price}"
                response += line + "\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {
                    "text": "\u2705 " + _t(lang, "Save", "Сохранить", "Guardar"),
                    "callback": f"doc_save:{pending_id}",
                },
                {
                    "text": "\u270f\ufe0f " + _t(lang, "Category", "Категория", "Categoria"),
                    "callback": f"receipt_correct:{pending_id}",
                },
                {
                    "text": "\u274c " + _t(lang, "Cancel", "Отмена", "Cancelar"),
                    "callback": "receipt_cancel",
                },
            ],
        )

    def _format_invoice(self, data: dict, pending_id: str, lang: str = "en") -> SkillResult:
        """Format invoice response."""
        try:
            invoice = InvoiceData(**data)
        except Exception:
            return self._format_generic(data, pending_id, lang)

        response = (
            "\U0001f4c4 <b>"
            + _t(lang, "Invoice recognized", "Инвойс распознан", "Factura reconocida")
            + "</b>\n\n"
        )
        vendor_lbl = _t(lang, "Vendor:", "Поставщик:", "Proveedor:")
        response += f"\U0001f3e2 <b>{vendor_lbl}</b> {invoice.vendor}\n"
        if invoice.invoice_number:
            num_lbl = _t(lang, "Number:", "Номер:", "Numero:")
            response += f"\U0001f522 <b>{num_lbl}</b> {invoice.invoice_number}\n"
        response += f"\U0001f4b5 <b>{_t(lang, 'Amount:', 'Сумма:', 'Monto:')}</b> ${invoice.total}"
        if invoice.currency and invoice.currency != "USD":
            response += f" {invoice.currency}"
        response += "\n"
        if invoice.subtotal:
            response += f"   {_t(lang, 'Subtotal', 'Подитог', 'Subtotal')}: ${invoice.subtotal}\n"
        if invoice.tax:
            response += f"   {_t(lang, 'Tax', 'Налог', 'Impuesto')}: ${invoice.tax}\n"
        if invoice.date:
            response += f"\U0001f4c5 <b>{_t(lang, 'Date:', 'Дата:', 'Fecha:')}</b> {invoice.date}\n"
        if invoice.due_date:
            due_lbl = _t(lang, "Due date:", "Срок оплаты:", "Fecha de pago:")
            response += f"\u23f0 <b>{due_lbl}</b> {invoice.due_date}\n"
        if invoice.items:
            response += f"\n\U0001f4cb <b>{_t(lang, 'Items:', 'Позиции:', 'Articulos:')}</b>\n"
            for item in invoice.items[:10]:
                desc = item.get("description", "\u2014")
                total = item.get("total", "")
                line = f"  \u2022 {desc}"
                if total:
                    line += f" \u2014 ${total}"
                response += line + "\n"
        if invoice.notes:
            notes_lbl = _t(lang, "Notes:", "Примечания:", "Notas:")
            response += f"\n\U0001f4dd <b>{notes_lbl}</b> {invoice.notes}\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {
                    "text": "\u2705 "
                    + _t(lang, "Save as expense", "Сохранить как расход", "Guardar como gasto"),
                    "callback": f"doc_save:{pending_id}",
                },
                {
                    "text": "\u274c " + _t(lang, "Cancel", "Отмена", "Cancelar"),
                    "callback": "receipt_cancel",
                },
            ],
        )

    def _format_rate_conf(self, data: dict, pending_id: str, lang: str = "en") -> SkillResult:
        """Format rate confirmation response."""
        try:
            load = LoadData(**data)
        except Exception:
            return self._format_generic(data, pending_id, lang)

        response = (
            "\U0001f69a <b>Rate Confirmation "
            + _t(lang, "recognized", "распознан", "reconocido")
            + "</b>\n\n"
        )
        response += f"\U0001f3e2 <b>{_t(lang, 'Broker:', 'Брокер:', 'Broker:')}</b> {load.broker}\n"
        response += f"\U0001f4b0 <b>{_t(lang, 'Rate:', 'Ставка:', 'Tarifa:')}</b> ${load.rate}\n"
        if load.ref_number:
            response += f"\U0001f522 <b>Ref #:</b> {load.ref_number}\n"
        response += f"\U0001f4cd <b>{_t(lang, 'Origin:', 'Откуда:', 'Origen:')}</b> {load.origin}\n"
        dest_lbl = _t(lang, "Destination:", "Куда:", "Destino:")
        response += f"\U0001f3c1 <b>{dest_lbl}</b> {load.destination}\n"
        if load.pickup_date:
            pickup_lbl = _t(lang, "Pickup:", "Пикап:", "Recogida:")
            response += f"\U0001f4c5 <b>{pickup_lbl}</b> {load.pickup_date}\n"
        if load.delivery_date:
            delivery_lbl = _t(lang, "Delivery:", "Доставка:", "Entrega:")
            response += f"\U0001f4e6 <b>{delivery_lbl}</b> {load.delivery_date}\n"

        return SkillResult(
            response_text=response,
            buttons=[
                {
                    "text": "\u2705 " + _t(lang, "Save load", "Сохранить груз", "Guardar carga"),
                    "callback": f"doc_save:{pending_id}",
                },
                {
                    "text": "\u274c " + _t(lang, "Cancel", "Отмена", "Cancelar"),
                    "callback": "receipt_cancel",
                },
            ],
        )

    def _format_generic(self, data: dict, pending_id: str, lang: str = "en") -> SkillResult:
        """Format generic document/image response."""
        try:
            doc = GenericDocumentData(**data)
        except Exception:
            doc = GenericDocumentData(
                summary=str(data)[:500],
                extracted_text=json.dumps(data, ensure_ascii=False)[:1000],
            )

        response = (
            "\U0001f4c4 <b>"
            + _t(lang, "Document recognized", "Документ распознан", "Documento reconocido")
            + "</b>\n\n"
        )
        if doc.title:
            response += (
                f"\U0001f4cc <b>{_t(lang, 'Title:', 'Заголовок:', 'Titulo:')}</b> {doc.title}\n"
            )
        if doc.doc_type:
            response += f"\U0001f4c1 <b>{_t(lang, 'Type:', 'Тип:', 'Tipo:')}</b> {doc.doc_type}\n"
        if doc.summary:
            desc_lbl = _t(lang, "Description:", "Описание:", "Descripcion:")
            response += f"\n\U0001f4dd <b>{desc_lbl}</b>\n{doc.summary}\n"
        if doc.key_values:
            response += (
                f"\n\U0001f511 <b>{_t(lang, 'Key data:', 'Ключевые данные:', 'Datos clave:')}</b>\n"
            )
            for k, v in list(doc.key_values.items())[:10]:
                response += f"  \u2022 {k}: {v}\n"
        if doc.amounts:
            response += (
                f"\n\U0001f4b0 <b>{_t(lang, 'Amounts:', 'Суммы:', 'Montos:')}</b> "
                + ", ".join(doc.amounts[:5])
                + "\n"
            )
        if doc.dates:
            response += (
                f"\U0001f4c5 <b>{_t(lang, 'Dates:', 'Даты:', 'Fechas:')}</b> "
                + ", ".join(doc.dates[:5])
                + "\n"
            )
        if doc.extracted_text and not doc.summary:
            text_preview = doc.extracted_text[:300]
            if len(doc.extracted_text) > 300:
                text_preview += "..."
            response += (
                f"\n<b>{_t(lang, 'Text:', 'Текст:', 'Texto:')}</b>\n<code>{text_preview}</code>\n"
            )

        return SkillResult(
            response_text=response,
            buttons=[
                {
                    "text": "\u2705 " + _t(lang, "Save", "Сохранить", "Guardar"),
                    "callback": f"doc_save:{pending_id}",
                },
                {
                    "text": "\u274c " + _t(lang, "Cancel", "Отмена", "Cancelar"),
                    "callback": "receipt_cancel",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CLASSIFY_PROMPT


skill = ScanDocumentSkill()
