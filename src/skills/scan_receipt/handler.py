"""Scan receipt skill — OCR photo → structured data → INSERT."""

import base64
import json
import logging
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.db import async_session, redis
from src.core.llm.clients import anthropic_client
from src.core.models.document import Document
from src.core.models.enums import DocumentType, Scope, TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.schemas.receipt import ReceiptData, ReceiptItem
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt
from src.tools.storage import upload_document

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "ask_photo": "Send a receipt photo to scan.",
        "ocr_failed": "Could not recognize the receipt. Try a clearer photo.",
        "fuel_header": "\u26fd\ufe0f <b>Fuel receipt recognized</b>\n\n",
        "receipt_header": "\U0001f9fe <b>Receipt recognized</b>\n\n",
        "auto_saved": "\n\n\u2705 Auto-saved (ID: {tx_id})",
        "label_merchant": "\U0001f3ea <b>Store:</b>",
        "label_total": "\U0001f4b5 <b>Total:</b>",
        "label_tax": "tax",
        "label_date": "\U0001f4c5 <b>Date:</b>",
        "label_fuel": "\u26fd\ufe0f <b>Fuel:</b>",
        "label_state": "\U0001f4cd <b>State:</b>",
        "label_items": "\U0001f4cb <b>Items:</b>",
        "saved_ok": "\u2705 Receipt saved!",
        "saved_ok_scope": "\u2705 Receipt saved! {scope_label}",
        "save_error": "Error saving receipt. Try again.",
        "receipt_expired": "Receipt data expired. Send the photo again.",
        "btn_correct": "\u2705 Correct",
        "btn_category": "\u270f\ufe0f Category",
        "btn_amount": "\U0001f4b0 Amount",
        "btn_cancel": "\u274c Cancel",
        "btn_business": "\U0001f3e2 Business",
        "btn_personal": "\U0001f3e0 Personal",
    },
    "ru": {
        "ask_photo": "Отправьте фото чека для распознавания.",
        "ocr_failed": "Не удалось распознать чек. Попробуйте сделать фото более чётким.",
        "fuel_header": "\u26fd\ufe0f <b>Заправочный чек распознан</b>\n\n",
        "receipt_header": "\U0001f9fe <b>Чек распознан</b>\n\n",
        "auto_saved": "\n\n\u2705 Автоматически сохранено (ID: {tx_id})",
        "label_merchant": "\U0001f3ea <b>Магазин:</b>",
        "label_total": "\U0001f4b5 <b>Сумма:</b>",
        "label_tax": "налог",
        "label_date": "\U0001f4c5 <b>Дата:</b>",
        "label_fuel": "\u26fd\ufe0f <b>Топливо:</b>",
        "label_state": "\U0001f4cd <b>Штат:</b>",
        "label_items": "\U0001f4cb <b>Товары:</b>",
        "saved_ok": "\u2705 Чек записан!",
        "saved_ok_scope": "\u2705 Чек записан! {scope_label}",
        "save_error": "Ошибка при записи чека. Попробуйте ещё раз.",
        "receipt_expired": "Данные чека истекли. Отправьте фото ещё раз.",
        "btn_correct": "\u2705 Верно",
        "btn_category": "\u270f\ufe0f Категория",
        "btn_amount": "\U0001f4b0 Сумма",
        "btn_cancel": "\u274c Отмена",
        "btn_business": "\U0001f3e2 Бизнес",
        "btn_personal": "\U0001f3e0 Личное",
    },
    "es": {
        "ask_photo": "Envia una foto del recibo para escanearlo.",
        "ocr_failed": "No se pudo reconocer el recibo. Intenta con una foto mas clara.",
        "fuel_header": "\u26fd\ufe0f <b>Recibo de combustible reconocido</b>\n\n",
        "receipt_header": "\U0001f9fe <b>Recibo reconocido</b>\n\n",
        "auto_saved": "\n\n\u2705 Guardado automaticamente (ID: {tx_id})",
        "label_merchant": "\U0001f3ea <b>Tienda:</b>",
        "label_total": "\U0001f4b5 <b>Total:</b>",
        "label_tax": "impuesto",
        "label_date": "\U0001f4c5 <b>Fecha:</b>",
        "label_fuel": "\u26fd\ufe0f <b>Combustible:</b>",
        "label_state": "\U0001f4cd <b>Estado:</b>",
        "label_items": "\U0001f4cb <b>Articulos:</b>",
        "saved_ok": "\u2705 Recibo guardado!",
        "saved_ok_scope": "\u2705 Recibo guardado! {scope_label}",
        "save_error": "Error al guardar el recibo. Intenta de nuevo.",
        "receipt_expired": "Los datos del recibo expiraron. Envia la foto de nuevo.",
        "btn_correct": "\u2705 Correcto",
        "btn_category": "\u270f\ufe0f Categoria",
        "btn_amount": "\U0001f4b0 Monto",
        "btn_cancel": "\u274c Cancelar",
        "btn_business": "\U0001f3e2 Negocio",
        "btn_personal": "\U0001f3e0 Personal",
    },
}
register_strings("scan_receipt", _STRINGS)

PENDING_RECEIPT_TTL = 3600  # 1 hour


async def store_pending_receipt(
    pending_id: str,
    receipt: ReceiptData,
    image_bytes: bytes | None,
    mime_type: str,
    user_id: str,
    family_id: str,
) -> None:
    """Store pending receipt data in Redis for later save on user confirm."""
    payload = {
        "receipt": receipt.model_dump(mode="json"),
        "image_b64": base64.b64encode(image_bytes).decode() if image_bytes else "",
        "mime_type": mime_type,
        "user_id": user_id,
        "family_id": family_id,
    }
    await redis.set(
        f"pending_receipt:{pending_id}", json.dumps(payload, default=str), ex=PENDING_RECEIPT_TTL
    )


async def get_pending_receipt(pending_id: str) -> dict | None:
    """Retrieve pending receipt data from Redis."""
    data = await redis.get(f"pending_receipt:{pending_id}")
    if not data:
        return None
    return json.loads(data)


async def delete_pending_receipt(pending_id: str) -> None:
    """Delete pending receipt data from Redis."""
    await redis.delete(f"pending_receipt:{pending_id}")


_DEFAULT_SYSTEM_PROMPT = """Проанализируй фото чека и извлеки данные в JSON:
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

OCR_PROMPT = _DEFAULT_SYSTEM_PROMPT


class ScanReceiptSkill:
    name = "scan_receipt"
    intents = ["scan_receipt"]
    model = "gemini-3.1-flash-lite-preview"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"

        if not message.photo_bytes and not message.photo_url:
            return SkillResult(
                response_text=t_cached(_STRINGS, "ask_photo", lang, "scan_receipt"),
            )

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
                    response_text=t_cached(
                        _STRINGS, "ocr_failed", lang, "scan_receipt"
                    ),
                )

        # Format detailed response for user (Telegram HTML)
        is_fuel = bool(receipt.gallons and receipt.price_per_gallon)

        if is_fuel:
            response = t_cached(_STRINGS, "fuel_header", lang, "scan_receipt")
        else:
            response = t_cached(_STRINGS, "receipt_header", lang, "scan_receipt")

        lm = t_cached(_STRINGS, "label_merchant", lang, "scan_receipt")
        lt = t_cached(_STRINGS, "label_total", lang, "scan_receipt")
        ltax = t_cached(_STRINGS, "label_tax", lang, "scan_receipt")
        ld = t_cached(_STRINGS, "label_date", lang, "scan_receipt")
        lf = t_cached(_STRINGS, "label_fuel", lang, "scan_receipt")
        ls = t_cached(_STRINGS, "label_state", lang, "scan_receipt")
        li = t_cached(_STRINGS, "label_items", lang, "scan_receipt")

        response += f"{lm} {receipt.merchant}\n"
        response += f"{lt} ${receipt.total}"
        if receipt.tax:
            response += f" ({ltax}: ${receipt.tax})"
        response += "\n"
        if receipt.date:
            response += f"{ld} {receipt.date}\n"
        if is_fuel:
            response += (
                f"{lf} {receipt.gallons} gal @ ${receipt.price_per_gallon}/gal\n"
            )
        if receipt.state:
            response += f"{ls} {receipt.state}\n"

        # Show items only for non-fuel receipts (fuel info is already above)
        if receipt.items and not is_fuel:
            response += f"\n{li}\n"
            for item in receipt.items[:10]:
                name = item.name if isinstance(item, ReceiptItem) else item.get("name", "—")
                qty = item.quantity if isinstance(item, ReceiptItem) else item.get("quantity", 1)
                price = item.price if isinstance(item, ReceiptItem) else item.get("price", 0)
                line = f"  • {name}"
                if qty and float(qty) != 1:
                    total_price = float(price) * float(qty)
                    line += f" ×{qty} — ${total_price:.2f}"
                elif price:
                    line += f" — ${price}"
                response += line + "\n"

        # Compute real confidence from OCR completeness
        confidence = self._compute_confidence(receipt)

        # Business users → always show scope selection (user decides business vs personal)
        if context.business_type:
            pending_id = str(uuid.uuid4())[:8]
            await store_pending_receipt(
                pending_id=pending_id,
                receipt=receipt,
                image_bytes=message.photo_bytes,
                mime_type="image/jpeg",
                user_id=context.user_id,
                family_id=context.family_id,
            )
            return SkillResult(
                response_text=response,
                buttons=[
                    {
                        "text": t_cached(
                            _STRINGS, "btn_business", lang, "scan_receipt",
                        ),
                        "callback": f"receipt_scope:{pending_id}:business",
                    },
                    {
                        "text": t_cached(
                            _STRINGS, "btn_personal", lang, "scan_receipt",
                        ),
                        "callback": f"receipt_scope:{pending_id}:family",
                    },
                    {
                        "text": t_cached(
                            _STRINGS, "btn_cancel", lang, "scan_receipt",
                        ),
                        "callback": f"receipt_cancel:{pending_id}",
                    },
                ],
            )

        # Non-business users: auto-save high-confidence receipts
        if confidence > Decimal("0.95"):
            try:
                tx_id = await self._save_receipt_to_db(
                    receipt,
                    context,
                    image_bytes=message.photo_bytes,
                    mime_type="image/jpeg",
                    confidence=confidence,
                )
                response += t_cached(
                    _STRINGS, "auto_saved", lang, "scan_receipt", tx_id=tx_id
                )
                return SkillResult(response_text=response)
            except Exception as e:
                logger.error("Auto-save receipt failed: %s", e)

        # Low confidence — store pending and show confirm buttons
        pending_id = str(uuid.uuid4())[:8]
        await store_pending_receipt(
            pending_id=pending_id,
            receipt=receipt,
            image_bytes=message.photo_bytes,
            mime_type="image/jpeg",
            user_id=context.user_id,
            family_id=context.family_id,
        )

        return SkillResult(
            response_text=response,
            buttons=[
                {
                    "text": t_cached(_STRINGS, "btn_correct", lang, "scan_receipt"),
                    "callback": f"receipt_confirm:{pending_id}",
                },
                {
                    "text": t_cached(_STRINGS, "btn_category", lang, "scan_receipt"),
                    "callback": f"receipt_correct:{pending_id}",
                },
                {
                    "text": t_cached(_STRINGS, "btn_amount", lang, "scan_receipt"),
                    "callback": f"receipt_amount:{pending_id}",
                },
                {
                    "text": t_cached(_STRINGS, "btn_cancel", lang, "scan_receipt"),
                    "callback": f"receipt_cancel:{pending_id}",
                },
            ],
        )

    @staticmethod
    def _compute_confidence(receipt: ReceiptData) -> Decimal:
        """Compute OCR confidence from field completeness.

        Scoring: merchant (0.30) + total (0.30) + date (0.20) + items (0.20).
        All core fields present → 1.0.  Missing fields lower the score.
        """
        score = Decimal("0")
        if receipt.merchant and receipt.merchant.strip():
            score += Decimal("0.30")
        if receipt.total and receipt.total > 0:
            score += Decimal("0.30")
        if receipt.date:
            score += Decimal("0.20")
        if receipt.items and len(receipt.items) > 0:
            score += Decimal("0.20")
        return score

    async def _save_receipt_to_db(
        self,
        receipt: ReceiptData,
        context: SessionContext,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
        confidence: Decimal = Decimal("0.9"),
    ) -> str:
        """Save receipt as Transaction + Document. Returns transaction ID."""
        # Upload image to Supabase Storage before opening the DB session
        storage_path = "pending"
        if image_bytes:
            storage_path = await upload_document(
                file_bytes=image_bytes,
                family_id=context.family_id,
                filename=f"receipt_{uuid.uuid4().hex[:8]}.jpg",
                mime_type=mime_type,
                bucket="documents",
            )

        async with async_session() as session:
            # 1. Create Document record
            doc = Document(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                type=DocumentType.receipt,
                storage_path=storage_path,
                ocr_model="gemini-3.1-flash-lite-preview",
                ocr_parsed=receipt.model_dump(mode="json"),
                ocr_confidence=confidence,
            )
            session.add(doc)
            await session.flush()

            # 2. Resolve category: merchant mapping → fuel detection → smart fallback
            category_id = self._resolve_category(receipt.merchant, context)

            # Auto-detect fuel: gallons must be ≥3 AND merchant must look like a fuel station
            # (prevents grocery store gallons like "2 gallons of milk" from triggering fuel category)
            if not category_id and receipt.gallons and float(receipt.gallons) >= 3:
                if _looks_like_fuel_station(receipt.merchant):
                    category_id = _find_fuel_category(
                        context, merchant=receipt.merchant, gallons=receipt.gallons,
                    )

            # Fallback: prefer matching scope category
            if not category_id:
                category_id = _fallback_category(context)

            # 3. Determine scope from resolved category
            resolved_scope = Scope.business if context.business_type else Scope.family
            for cat in context.categories:
                if cat["id"] == category_id:
                    resolved_scope = Scope(cat.get("scope", "family"))
                    break

            # 4. Create Transaction
            tx = Transaction(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                category_id=uuid.UUID(category_id),
                type=TransactionType.expense,
                amount=receipt.total,
                merchant=receipt.merchant,
                date=date.fromisoformat(receipt.date) if receipt.date else date.today(),
                scope=resolved_scope,
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
                ai_confidence=confidence,
            )
            session.add(tx)
            await session.commit()
            return str(tx.id)

    @observe(name="ocr_gemini")
    async def _ocr_gemini(self, message: IncomingMessage) -> ReceiptData:
        parts = [OCR_PROMPT]
        if message.photo_bytes:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(message.photo_bytes).decode(),
                    }
                }
            )

        from src.core.llm.clients import gemini_generate_content

        response = await gemini_generate_content(
            model="gemini-3.1-flash-lite-preview",
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
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        return ReceiptData(**data)

    def _resolve_category(self, merchant: str, context: SessionContext) -> str | None:
        """Resolve category ID from merchant_mappings in context."""
        if not merchant or not context.merchant_mappings:
            return None
        merchant_lower = merchant.lower()
        for mapping in context.merchant_mappings:
            pattern = mapping.get("merchant_pattern", "").lower()
            if pattern and pattern in merchant_lower:
                return mapping.get("category_id")
        return None

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        return prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)


# Keywords that confirm a merchant is a fuel/gas station
_FUEL_STATION_KEYWORDS = {
    "gas", "fuel", "diesel", "petro", "gasoline", "station", "shell", "exxon",
    "bp ", "chevron", "mobil", "marathon", "sunoco", "arco", "valero", "citgo",
    "speedway", "kwik", "wawa", "casey", "circle k", "loves", "pilot", "flying j",
    "ta truck", "ambest", "sapp bros", "заправка", "азс", "нефть",
}


def _looks_like_fuel_station(merchant: str | None) -> bool:
    """Return True if the merchant name suggests a fuel/gas station."""
    if not merchant:
        return False
    ml = merchant.lower()
    return any(kw in ml for kw in _FUEL_STATION_KEYWORDS)


_FUEL_NAMES = {"дизель", "diesel", "fuel", "топливо", "gasoline", "бензин"}

# Truck stops → always commercial fuel (business scope)
_TRUCK_STOP_PATTERNS = {"pilot", "loves", "flying j", "ta ", "petro", "ambest", "sapp bros"}

# Gallons threshold: above this → likely commercial vehicle (truck, taxi fleet)
_COMMERCIAL_GALLONS_THRESHOLD = 25


def _is_commercial_fuel(merchant: str | None, gallons: float | None) -> bool:
    """Determine if fuel purchase is commercial (truck/taxi) vs personal (family car).

    Commercial indicators:
    - Merchant is a truck stop (Pilot, Loves, Flying J, TA, Petro)
    - Large fill: >25 gallons (trucks fill 100-300 gal, cars fill 10-18 gal)

    Personal: regular gas stations (Costco, Shell, BP) with small fills.
    """
    if merchant:
        merchant_lower = merchant.lower()
        for pattern in _TRUCK_STOP_PATTERNS:
            if pattern in merchant_lower:
                return True
    if gallons and gallons > _COMMERCIAL_GALLONS_THRESHOLD:
        return True
    return False


def _find_fuel_category(
    context: SessionContext,
    merchant: str | None = None,
    gallons: float | None = None,
) -> str | None:
    """Find the best fuel category based on commercial vs personal detection.

    Commercial fuel (truck stops / large fills) → business-scope fuel category.
    Personal fuel (regular stations / small fills) → family-scope fuel category.
    Falls back to any fuel category if the preferred scope isn't found.
    """
    is_commercial = _is_commercial_fuel(merchant, gallons)
    preferred_scope = "business" if is_commercial else "family"
    fallback_scope = "business" if not is_commercial else "family"

    # First pass: preferred scope
    for cat in context.categories:
        if cat.get("scope") == preferred_scope and cat["name"].lower() in _FUEL_NAMES:
            return cat["id"]

    # Second pass: fallback scope (any fuel category is better than none)
    for cat in context.categories:
        if cat.get("scope") == fallback_scope and cat["name"].lower() in _FUEL_NAMES:
            return cat["id"]

    return None


def _fallback_category(context: SessionContext) -> str:
    """Pick best fallback category: prefer matching scope, then first available."""
    scope = "business" if context.business_type else "family"
    for cat in context.categories:
        if cat.get("scope") == scope:
            return cat["id"]
    return context.categories[0]["id"]


skill = ScanReceiptSkill()
