"""Generate invoice skill — unified: preview → confirm → PDF.

Flow:
1. Parse user text with LLM to extract items, contact, dates
2. Resolve contact from DB (fuzzy match)
3. Build line items from user text and/or DB transactions
4. Show preview with confirm/edit/cancel buttons (Redis pending)
5. On confirm callback → generate PDF via WeasyPrint, save Invoice to DB
"""

import json
import logging
import re
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from jinja2 import BaseLoader, Environment, select_autoescape
from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session, redis
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.models.contact import Contact
from src.core.models.enums import InvoiceStatus, TransactionType
from src.core.models.invoice import Invoice
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.search_utils import ilike_all_words, split_search_words
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

PENDING_INVOICE_TTL = 600  # 10 minutes


class InvoiceDraftState(StrEnum):
    collect_seller = "collect_seller"
    collect_buyer = "collect_buyer"
    collect_items = "collect_items"
    await_confirm = "await_confirm"
    confirmed = "confirmed"
    cancelled = "cancelled"

# ---------------------------------------------------------------------------
# i18n strings
# ---------------------------------------------------------------------------
_STRINGS = {
    "en": {
        "no_account": "Set up your account first to generate invoices.",
        "ask_who": (
            "Who should I invoice? Tell me the client name and what to include.\n"
            'Example: "invoice Mike Chen for plumbing repair $500"'
        ),
        "need_seller_fields": "Before creating invoice, provide seller data:\n{fields}",
        "need_buyer_fields": "Need buyer data:\n{fields}",
        "buyer_choices": "Found multiple contacts for <b>{name}</b>:\n{options}\nSend exact name.",
        "buyer_created": "Created new buyer contact: <b>{name}</b>.",
        "no_contact": (
            "I don't have <b>{name}</b> in your contacts. "
            'Add them first: "add contact {name}"'
        ),
        "no_items": (
            "No items to invoice. Tell me what to include:\n"
            '• "invoice Mike for plumbing $500, parts $150"\n'
            '• "invoice Sarah for this month\'s work"'
        ),
        "need_item_details": (
            "Send invoice items like:\n"
            "• item: Plumbing repair, qty: 1, price: 500\n"
            "• item: Pipe parts, qty: 2, price: 75"
        ),
        "preview_header": "📋 <b>Invoice Preview #{number}</b>",
        "preview_client": "Client: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Total: {symbol}{total}</b>",
        "preview_subtotal": "Subtotal: {symbol}{subtotal}",
        "preview_tax_pending": "Sales tax: calculated on confirmation",
        "preview_tax": "Sales tax ({rate}%): {symbol}{tax}",
        "preview_due": "Due: {date}",
        "preview_notes": "Notes: {notes}",
        "btn_confirm": "✅ Generate PDF",
        "btn_edit": "✏️ Edit",
        "btn_cancel": "❌ Cancel",
        "expired": "Invoice preview expired. Please try again.",
        "not_allowed": "This invoice draft belongs to another user.",
        "cancelled": "Invoice cancelled.",
        "generated": (
            "📄 <b>Invoice #{number}</b>\n"
            "Client: {name}\n"
            "Total: {symbol}{total}\n"
            "Due: {due}"
        ),
        "pdf_failed": "Failed to generate PDF. Please try again.",
        "tax_missing_address": (
            "To calculate US sales tax, send buyer address fields: state and ZIP code."
        ),
        "tax_provider_unavailable": "Tax provider is not configured. Try again later.",
        "tax_provider_error": "Couldn't calculate sales tax right now. Please retry.",
        "tax_no_taxable_items": "No taxable items found in this invoice.",
        "tax_invalid_subtotal": "Invoice subtotal is invalid for tax calculation.",
        "edit_hint": (
            "Send corrections:\n"
            "• Add: 'add: description $100'\n"
            "• Remove: 'remove 2'\n"
            "• Due date: 'due: 15 days'"
        ),
    },
    "ru": {
        "no_account": "Сначала настройте аккаунт для создания инвойсов.",
        "ask_who": (
            "Кому выставить счёт? Укажи клиента и что включить.\n"
            'Пример: "инвойс для Mike Chen за ремонт $500"'
        ),
        "need_seller_fields": "Перед созданием инвойса укажите данные продавца:\n{fields}",
        "need_buyer_fields": "Нужны данные покупателя:\n{fields}",
        "buyer_choices": (
            "Найдено несколько контактов для <b>{name}</b>:\n{options}\n"
            "Отправьте точное имя."
        ),
        "buyer_created": "Новый контакт покупателя создан: <b>{name}</b>.",
        "no_contact": (
            "Контакт <b>{name}</b> не найден. "
            'Сначала добавьте: "добавь контакт {name}"'
        ),
        "no_items": (
            "Нет позиций для инвойса. Укажите что включить:\n"
            '• "инвойс Mike за ремонт $500, запчасти $150"\n'
            '• "инвойс Sarah за работу в этом месяце"'
        ),
        "need_item_details": (
            "Пришлите позиции инвойса в формате:\n"
            "• item: Ремонт, qty: 1, price: 500\n"
            "• item: Запчасти, qty: 2, price: 75"
        ),
        "preview_header": "📋 <b>Предпросмотр инвойса #{number}</b>",
        "preview_client": "Клиент: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Итого: {symbol}{total}</b>",
        "preview_subtotal": "Подытог: {symbol}{subtotal}",
        "preview_tax_pending": "Налог с продаж: будет рассчитан при подтверждении",
        "preview_tax": "Налог с продаж ({rate}%): {symbol}{tax}",
        "preview_due": "Оплатить до: {date}",
        "preview_notes": "Примечание: {notes}",
        "btn_confirm": "✅ Создать PDF",
        "btn_edit": "✏️ Изменить",
        "btn_cancel": "❌ Отменить",
        "expired": "Предпросмотр истёк. Попробуйте снова.",
        "not_allowed": "Этот черновик инвойса принадлежит другому пользователю.",
        "cancelled": "Инвойс отменён.",
        "generated": (
            "📄 <b>Инвойс #{number}</b>\n"
            "Клиент: {name}\n"
            "Итого: {symbol}{total}\n"
            "Оплатить до: {due}"
        ),
        "pdf_failed": "Не удалось создать PDF. Попробуйте снова.",
        "tax_missing_address": (
            "Чтобы рассчитать налог с продаж в США, пришлите штат и ZIP покупателя."
        ),
        "tax_provider_unavailable": "Налоговый провайдер не настроен. Попробуйте позже.",
        "tax_provider_error": "Не удалось рассчитать налог. Повторите попытку.",
        "tax_no_taxable_items": "В инвойсе нет налогооблагаемых позиций.",
        "tax_invalid_subtotal": "Некорректный подытог инвойса для расчёта налога.",
        "edit_hint": (
            "Отправьте исправления:\n"
            "• Добавить: 'добавить: описание $100'\n"
            "• Удалить: 'удалить 2'\n"
            "• Срок оплаты: 'срок: 15 дней'"
        ),
    },
    "es": {
        "no_account": "Configure su cuenta primero para generar facturas.",
        "ask_who": (
            "¿A quién debo facturar? Dime el cliente y qué incluir.\n"
            'Ejemplo: "factura para Mike Chen por reparación $500"'
        ),
        "need_seller_fields": "Antes de crear la factura, envia datos del vendedor:\n{fields}",
        "need_buyer_fields": "Faltan datos del cliente:\n{fields}",
        "buyer_choices": (
            "Encontré varios contactos para <b>{name}</b>:\n{options}\n"
            "Envia el nombre exacto."
        ),
        "buyer_created": "Se creó el contacto del cliente: <b>{name}</b>.",
        "no_contact": (
            "No tengo a <b>{name}</b> en tus contactos. "
            'Agrégalo primero: "agregar contacto {name}"'
        ),
        "no_items": (
            "No hay elementos para facturar. Dime qué incluir:\n"
            '• "factura Mike por plomería $500, materiales $150"\n'
            '• "factura Sarah por el trabajo de este mes"'
        ),
        "need_item_details": (
            "Envia partidas así:\n"
            "• item: Reparación, qty: 1, price: 500\n"
            "• item: Materiales, qty: 2, price: 75"
        ),
        "preview_header": "📋 <b>Vista previa de factura #{number}</b>",
        "preview_client": "Cliente: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Total: {symbol}{total}</b>",
        "preview_subtotal": "Subtotal: {symbol}{subtotal}",
        "preview_tax_pending": "Impuesto de ventas: se calculara al confirmar",
        "preview_tax": "Impuesto de ventas ({rate}%): {symbol}{tax}",
        "preview_due": "Vencimiento: {date}",
        "preview_notes": "Notas: {notes}",
        "btn_confirm": "✅ Generar PDF",
        "btn_edit": "✏️ Editar",
        "btn_cancel": "❌ Cancelar",
        "expired": "La vista previa expiró. Inténtalo de nuevo.",
        "not_allowed": "Este borrador de factura pertenece a otro usuario.",
        "cancelled": "Factura cancelada.",
        "generated": (
            "📄 <b>Factura #{number}</b>\n"
            "Cliente: {name}\n"
            "Total: {symbol}{total}\n"
            "Vencimiento: {due}"
        ),
        "pdf_failed": "No se pudo generar el PDF. Inténtalo de nuevo.",
        "tax_missing_address": (
            "Para calcular impuesto en EE.UU., envia estado y codigo postal del cliente."
        ),
        "tax_provider_unavailable": "El proveedor de impuestos no está configurado.",
        "tax_provider_error": "No se pudo calcular el impuesto. Inténtalo de nuevo.",
        "tax_no_taxable_items": "No hay partidas gravables en esta factura.",
        "tax_invalid_subtotal": "Subtotal inválido para calcular impuesto.",
        "edit_hint": (
            "Envía correcciones:\n"
            "• Agregar: 'agregar: descripción $100'\n"
            "• Eliminar: 'eliminar 2'\n"
            "• Fecha de vencimiento: 'vence: 15 días'"
        ),
    },
}
register_strings("generate_invoice", _STRINGS)

# ---------------------------------------------------------------------------
# LLM extraction prompt
# ---------------------------------------------------------------------------
_EXTRACT_PROMPT = """\
Extract invoice details from the user's message. Return JSON only.
Current date: {today}. User's currency: {currency}.

Output format:
{{
  "contact_name": "client name or null",
  "items": [
    {{"description": "service/item", "quantity": 1, "unit_price": 500.0}}
  ],
  "due_days": 30,
  "notes": null
}}

Rules:
- items may be empty [] if user doesn't specify amounts (we'll pull from DB)
- quantity defaults to 1 if not specified
- due_days defaults to 30 if not specified
- Return ONLY valid JSON, no markdown fences"""

GENERATE_INVOICE_SYSTEM_PROMPT = """\
You help users create professional invoices.
Extract: client name, line items with amounts, due date, notes.
Current date/time in user's timezone ({timezone}): {now_local}.
ALWAYS respond in the same language as the user's message/query."""

# ---------------------------------------------------------------------------
# HTML template for PDF (moved from generate_invoice_pdf)
# ---------------------------------------------------------------------------
INVOICE_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: Arial, sans-serif; margin: 40px; color: #333; font-size: 14px; }
  .header { display: flex; justify-content: space-between; margin-bottom: 30px; }
  .company { font-size: 20px; font-weight: bold; color: #2c3e50; }
  .invoice-title { font-size: 28px; color: #3498db; text-align: right; }
  .invoice-number { color: #666; text-align: right; }
  .addresses { display: flex; justify-content: space-between; margin: 20px 0 30px; }
  .address-block { width: 45%; }
  .address-block h3 { color: #2980b9; margin-bottom: 5px; font-size: 12px;
                       text-transform: uppercase; }
  table { width: 100%; border-collapse: collapse; margin: 20px 0; }
  th { background: #3498db; color: white; padding: 10px; text-align: left; }
  td { padding: 8px 10px; border-bottom: 1px solid #ddd; }
  .amount { text-align: right; }
  .total-row { font-weight: bold; background: #ebf5fb; }
  .total-amount { font-size: 18px; color: #2c3e50; }
  .footer { margin-top: 40px; font-size: 11px; color: #999;
            border-top: 1px solid #ddd; padding-top: 10px; }
  .due-date { color: #e74c3c; font-weight: bold; }
</style>
</head>
<body>
  <div class="header">
    <div>
      <div class="company">{{ company_name }}</div>
      {% if company_address %}<div>{{ company_address }}</div>{% endif %}
      {% if company_phone %}<div>{{ company_phone }}</div>{% endif %}
    </div>
    <div>
      <div class="invoice-title">INVOICE</div>
      <div class="invoice-number">#{{ invoice_number }}</div>
    </div>
  </div>

  <div class="addresses">
    <div class="address-block">
      <h3>Bill To</h3>
      <div><b>{{ client_name }}</b></div>
      {% if client_email %}<div>{{ client_email }}</div>{% endif %}
      {% if client_phone %}<div>{{ client_phone }}</div>{% endif %}
    </div>
    <div class="address-block">
      <h3>Invoice Details</h3>
      <div>Date: {{ invoice_date }}</div>
      <div class="due-date">Due: {{ due_date }}</div>
      <div>Currency: {{ currency }}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Description</th>
        <th class="amount">Qty</th>
        <th class="amount">Unit Price</th>
        <th class="amount">Amount</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ item.description }}</td>
        <td class="amount">{{ item.quantity }}</td>
        <td class="amount">{{ "%.2f"|format(item.unit_price) }}</td>
        <td class="amount">{{ "%.2f"|format(item.amount) }}</td>
      </tr>
      {% endfor %}
      <tr class="total-row">
        <td colspan="4"><b>Subtotal</b></td>
        <td class="amount">
          <b>{{ currency_symbol }}{{ "%.2f"|format(subtotal) }}</b>
        </td>
      </tr>
      {% if tax_amount and tax_amount > 0 %}
      <tr class="total-row">
        <td colspan="4"><b>Sales Tax ({{ "%.2f"|format((tax_rate or 0) * 100) }}%)</b></td>
        <td class="amount">
          <b>{{ currency_symbol }}{{ "%.2f"|format(tax_amount) }}</b>
        </td>
      </tr>
      {% endif %}
      <tr class="total-row">
        <td colspan="4"><b>Total Due</b></td>
        <td class="amount total-amount">
          <b>{{ currency_symbol }}{{ "%.2f"|format(total) }}</b>
        </td>
      </tr>
    </tbody>
  </table>

  {% if notes %}
  <div style="margin-top: 20px;">
    <b>Notes:</b> {{ notes }}
  </div>
  {% endif %}

  <div class="footer">
    Generated by AI Assistant — {{ invoice_date }}
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Redis pending helpers
# ---------------------------------------------------------------------------
async def store_pending_invoice(pending_id: str, data: dict) -> None:
    try:
        await redis.set(
            f"invoice_pending:{pending_id}",
            json.dumps(data, default=str),
            ex=PENDING_INVOICE_TTL,
        )
        user_id = str(data.get("user_id", "")).strip()
        if user_id:
            await redis.set(f"invoice_active:{user_id}", pending_id, ex=PENDING_INVOICE_TTL)
    except Exception:
        logger.warning("Failed to store pending invoice in Redis", exc_info=True)


async def get_pending_invoice(pending_id: str) -> dict | None:
    try:
        raw = await redis.get(f"invoice_pending:{pending_id}")
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        logger.warning("Failed to load pending invoice from Redis", exc_info=True)
        return None


async def get_active_pending_invoice_id(user_id: str) -> str | None:
    try:
        return await redis.get(f"invoice_active:{user_id}")
    except Exception:
        logger.warning("Failed to load active invoice draft id from Redis", exc_info=True)
        return None


async def get_active_pending_invoice(user_id: str) -> dict | None:
    pending_id = await get_active_pending_invoice_id(user_id)
    if not pending_id:
        return None
    data = await get_pending_invoice(pending_id)
    if not data:
        try:
            await redis.delete(f"invoice_active:{user_id}")
        except Exception:
            logger.warning("Failed to clear stale active invoice pointer", exc_info=True)
        return None
    return data


async def delete_pending_invoice(pending_id: str, user_id: str | None = None) -> None:
    try:
        if user_id is None:
            existing = await get_pending_invoice(pending_id)
            if existing:
                user_id = str(existing.get("user_id", "")).strip() or None
        await redis.delete(f"invoice_pending:{pending_id}")
        if user_id:
            active_key = f"invoice_active:{user_id}"
            active_pid = await redis.get(active_key)
            if active_pid == pending_id:
                await redis.delete(active_key)
    except Exception:
        logger.warning("Failed to delete pending invoice from Redis", exc_info=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _generate_invoice_number() -> str:
    today = date.today()
    short_id = uuid.uuid4().hex[:4].upper()
    return f"{today.strftime('%Y%m')}-{short_id}"


def _currency_symbol(currency: str) -> str:
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽"}
    return symbols.get(currency, currency + " ")


def _parse_money(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return default


def _parse_due_days(value: Any, default: int = 30) -> int:
    try:
        parsed = int(value)
        if 1 <= parsed <= 365:
            return parsed
    except (TypeError, ValueError):
        pass
    return default


def _normalize_invoice_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize LLM-extracted line items; ignore malformed entries."""
    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        qty_raw = item.get("quantity", 1)
        unit_raw = item.get("unit_price", item.get("amount", 0))
        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            qty = 1
        unit_price = _parse_money(unit_raw)
        if unit_price < 0:
            unit_price = Decimal("0")
        amount = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        normalized.append({
            "description": description,
            "quantity": qty,
            "unit_price": float(unit_price),
            "amount": float(amount),
        })
    return normalized


def _requires_sales_tax(context: SessionContext, intent_data: dict[str, Any]) -> bool:
    profile_tax = {}
    if context.profile_config and isinstance(getattr(context.profile_config, "tax", None), dict):
        profile_tax = context.profile_config.tax or {}
    return bool(
        intent_data.get("requires_sales_tax")
        or profile_tax.get("collect_sales_tax")
        or profile_tax.get("sales_tax_required")
    )


def _extract_seller_state(context: SessionContext, intent_data: dict[str, Any]) -> str:
    profile_tax = {}
    if context.profile_config and isinstance(getattr(context.profile_config, "tax", None), dict):
        profile_tax = context.profile_config.tax or {}
    return (
        str(intent_data.get("seller_state") or profile_tax.get("seller_state") or "")
        .strip()
        .upper()
    )


def is_pending_invoice_owner(invoice_data: dict[str, Any], context: SessionContext) -> bool:
    return (
        str(invoice_data.get("user_id", "")).strip() == str(context.user_id).strip()
        and str(invoice_data.get("family_id", "")).strip() == str(context.family_id).strip()
    )


def _extract_fsm_hints_from_text(text: str) -> dict[str, Any]:
    """Parse explicit key:value hints from follow-up messages in draft workflow."""
    hints: dict[str, Any] = {}
    if not text:
        return hints
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    item_rows: list[dict[str, Any]] = []
    email_re = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
    phone_re = re.compile(r"\+?[0-9][0-9\-\s()]{6,}")
    for line in lines:
        if ":" not in line:
            # Fallback: detect email/phone anywhere in line
            email_match = email_re.search(line)
            if email_match and "contact_email" not in hints:
                hints["contact_email"] = email_match.group(0)
            phone_match = phone_re.search(line)
            if phone_match and "contact_phone" not in hints:
                hints["contact_phone"] = phone_match.group(0).strip()
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if not value:
            continue

        if key in {"company", "company_name"}:
            hints["company_name"] = value
        elif key in {"company_address", "seller_address", "address"}:
            hints["company_address"] = value
        elif key in {"seller_state", "state"}:
            hints["seller_state"] = value.upper()
        elif key in {"buyer", "buyer_name", "contact_name", "client"}:
            hints["contact_name"] = value
        elif key in {"buyer_email", "client_email", "contact_email", "email"}:
            hints["contact_email"] = value
        elif key in {"buyer_phone", "client_phone", "contact_phone", "phone"}:
            hints["contact_phone"] = value
        elif key in {"buyer_address", "buyer_address_line1"}:
            hints["buyer_address_line1"] = value
        elif key in {"buyer_city", "city"}:
            hints["buyer_city"] = value
        elif key in {"buyer_state"}:
            hints["buyer_state"] = value.upper()
        elif key in {"buyer_zip", "buyer_postal_code", "zip", "postal"}:
            hints["buyer_postal_code"] = value
        elif key in {"buyer_country", "country"}:
            hints["buyer_country"] = value.upper()
        elif key in {"due_days", "net", "invoice_due_days"}:
            hints["invoice_due_days"] = value
        elif key in {"note", "notes", "invoice_notes"}:
            hints["invoice_notes"] = value
        elif key in {"sales_tax", "requires_sales_tax"}:
            hints["requires_sales_tax"] = value.lower() in {"1", "true", "yes", "y", "да"}
        elif key in {"item", "line", "line_item"}:
            # Format: item: Description, qty: 2, price: 99.5
            parts = [p.strip() for p in value.split(",") if p.strip()]
            row: dict[str, Any] = {"description": parts[0] if parts else value}
            for p in parts[1:]:
                if ":" not in p:
                    continue
                k2, v2 = p.split(":", 1)
                k2 = k2.strip().lower()
                v2 = v2.strip()
                if k2 in {"qty", "quantity"}:
                    row["quantity"] = v2
                elif k2 in {"price", "unit_price", "amount"}:
                    row["unit_price"] = v2
            item_rows.append(row)

    if item_rows:
        hints["invoice_items"] = item_rows
    return hints


def _field_label(field: str, lang: str) -> str:
    labels = {
        "en": {
            "company_name": "company_name",
            "company_address": "company_address",
            "seller_state": "seller_state (US state code)",
            "contact_name": "buyer_name",
            "contact_email": "buyer_email",
            "contact_phone": "buyer_phone",
            "buyer_address_line1": "buyer_address",
            "buyer_city": "buyer_city",
            "buyer_state": "buyer_state",
            "buyer_postal_code": "buyer_zip",
        },
        "ru": {
            "company_name": "company_name (название компании)",
            "company_address": "company_address (адрес продавца)",
            "seller_state": "seller_state (штат продавца)",
            "contact_name": "buyer_name (имя покупателя)",
            "contact_email": "buyer_email",
            "contact_phone": "buyer_phone",
            "buyer_address_line1": "buyer_address",
            "buyer_city": "buyer_city",
            "buyer_state": "buyer_state",
            "buyer_postal_code": "buyer_zip",
        },
        "es": {
            "company_name": "company_name",
            "company_address": "company_address",
            "seller_state": "seller_state (estado del vendedor)",
            "contact_name": "buyer_name",
            "contact_email": "buyer_email",
            "contact_phone": "buyer_phone",
            "buyer_address_line1": "buyer_address",
            "buyer_city": "buyer_city",
            "buyer_state": "buyer_state",
            "buyer_postal_code": "buyer_zip",
        },
    }
    return labels.get(lang, labels["en"]).get(field, field)


def _format_missing_fields(fields: list[str], lang: str) -> str:
    return "\n".join(f"• <code>{_field_label(field, lang)}: ...</code>" for field in fields)


def _resolve_contact_name_from_candidates(
    text: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lowered = text.strip().lower()
    if not lowered:
        return None
    if lowered.isdigit():
        idx = int(lowered) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    for candidate in candidates:
        if candidate["name"].strip().lower() == lowered:
            return candidate
    return None


async def _parse_invoice_request(
    text: str, currency: str,
) -> dict:
    """Use Claude Sonnet to extract invoice items from free text."""
    today = date.today().isoformat()
    system = _EXTRACT_PROMPT.format(today=today, currency=currency)

    client = anthropic_client()
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": text}],
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            **prompt_data,
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw)
    except Exception:
        logger.warning("Invoice extraction failed, returning empty", exc_info=True)
        return {"contact_name": None, "items": [], "due_days": 30, "notes": None}


async def _find_contacts(family_id: str, name: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find contacts by fuzzy name match."""
    async with async_session() as session:
        words = split_search_words(name)
        name_filter = (
            ilike_all_words(Contact.name, words) if words else Contact.name.ilike(f"%{name}%")
        )
        stmt = (
            select(Contact)
            .where(Contact.family_id == uuid.UUID(family_id), name_filter)
            .order_by(Contact.name.asc())
            .limit(limit)
        )
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "email": r.email,
                "phone": r.phone,
            }
            for r in rows
        ]


async def _find_contact_by_id(family_id: str, contact_id: str) -> dict[str, Any] | None:
    async with async_session() as session:
        stmt = select(Contact).where(
            Contact.family_id == uuid.UUID(family_id),
            Contact.id == uuid.UUID(contact_id),
        )
        row = await session.scalar(stmt)
        if not row:
            return None
        return {
            "id": str(row.id),
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
        }


async def _create_contact(
    *,
    family_id: str,
    user_id: str,
    name: str,
    email: str | None,
    phone: str | None,
) -> dict[str, Any]:
    async with async_session() as session:
        row = Contact(
            id=uuid.uuid4(),
            family_id=uuid.UUID(family_id),
            user_id=uuid.UUID(user_id),
            name=name,
            email=email or None,
            phone=phone or None,
        )
        session.add(row)
        await session.commit()
        return {
            "id": str(row.id),
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
        }


async def _pull_contact_transactions(
    family_id: str,
    contact: dict,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Pull income transactions linked to contact. NO fallback to all income."""
    cutoff_start = (
        date.fromisoformat(date_from) if date_from else date.today() - timedelta(days=30)
    )
    cutoff_end = date.fromisoformat(date_to) if date_to else date.today()
    fid = uuid.UUID(family_id)
    contact_id = uuid.UUID(contact["id"])

    async with async_session() as session:
        # Primary: match by contact_id FK
        stmt = (
            select(Transaction)
            .where(
                Transaction.family_id == fid,
                Transaction.type == TransactionType.income,
                Transaction.contact_id == contact_id,
                Transaction.date >= cutoff_start,
                Transaction.date <= cutoff_end,
            )
            .order_by(Transaction.date.desc())
            .limit(50)
        )
        rows = (await session.scalars(stmt)).all()

        # Fallback: merchant ILIKE (but NOT all income)
        if not rows:
            stmt_merchant = (
                select(Transaction)
                .where(
                    Transaction.family_id == fid,
                    Transaction.type == TransactionType.income,
                    Transaction.merchant.ilike(f"%{contact['name']}%"),
                    Transaction.date >= cutoff_start,
                    Transaction.date <= cutoff_end,
                )
                .order_by(Transaction.date.desc())
                .limit(50)
            )
            rows = (await session.scalars(stmt_merchant)).all()

        return [
            {
                "description": r.merchant or r.description or "Service",
                "quantity": 1,
                "unit_price": float(r.amount),
                "amount": float(r.amount),
                "date": r.date.isoformat(),
                "transaction_id": str(r.id),
            }
            for r in rows
        ]


def _format_preview(invoice_data: dict, lang: str) -> str:
    """Format invoice preview for Telegram display."""
    parts = [
        t(_STRINGS, "preview_header", lang, number=invoice_data["invoice_number"]),
        t(_STRINGS, "preview_client", lang, name=invoice_data["client_name"]),
    ]
    if invoice_data.get("client_email"):
        parts.append(t(_STRINGS, "preview_email", lang, email=invoice_data["client_email"]))

    parts.append("")
    for i, item in enumerate(invoice_data["items"], 1):
        qty = item.get("quantity", 1)
        unit = item.get("unit_price", item.get("amount", 0))
        amount = item.get("amount", qty * unit)
        line = f"{i}. {item['description']}"
        if qty > 1:
            line += f" ×{qty}"
        line += f" — {invoice_data['currency_symbol']}{amount:.2f}"
        parts.append(line)

    parts.append(
        t(
            _STRINGS,
            "preview_total",
            lang,
            symbol=invoice_data["currency_symbol"],
            total=f"{invoice_data['total']:.2f}",
        )
    )
    if invoice_data.get("subtotal") is not None:
        parts.append(
            t(
                _STRINGS,
                "preview_subtotal",
                lang,
                symbol=invoice_data["currency_symbol"],
                subtotal=f"{invoice_data['subtotal']:.2f}",
            )
        )
    if invoice_data.get("requires_sales_tax"):
        if invoice_data.get("tax_amount", 0) > 0:
            parts.append(
                t(
                    _STRINGS,
                    "preview_tax",
                    lang,
                    rate=f"{(invoice_data.get('tax_rate', 0) * 100):.2f}",
                    symbol=invoice_data["currency_symbol"],
                    tax=f"{invoice_data.get('tax_amount', 0):.2f}",
                )
            )
        else:
            parts.append(t(_STRINGS, "preview_tax_pending", lang))
    parts.append(t(_STRINGS, "preview_due", lang, date=invoice_data["due_date"]))

    if invoice_data.get("notes"):
        parts.append(t(_STRINGS, "preview_notes", lang, notes=invoice_data["notes"]))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------
class GenerateInvoiceSkill:
    name = "generate_invoice"
    intents = ["generate_invoice"]
    model = "claude-sonnet-4-6"

    @observe(name="skill_generate_invoice")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        family_id = context.family_id
        lang = context.language or "en"

        if not family_id:
            return SkillResult(response_text=t(_STRINGS, "no_account", lang))

        user_text = message.text or ""
        hints = _extract_fsm_hints_from_text(user_text)
        merged = {**intent_data, **hints}

        active_draft = await get_active_pending_invoice(context.user_id)
        if active_draft and user_text.strip().lower() in {"cancel", "отмена", "cancel invoice"}:
            pending_id = active_draft.get("pending_id")
            if pending_id:
                await delete_pending_invoice(pending_id, user_id=context.user_id)
            return SkillResult(response_text=t(_STRINGS, "cancelled", lang))
        if (
            active_draft
            and active_draft.get("draft_state") == InvoiceDraftState.await_confirm.value
            and (merged.get("contact_name") or merged.get("invoice_items"))
        ):
            await delete_pending_invoice(
                active_draft.get("pending_id", ""),
                user_id=context.user_id,
            )
            active_draft = None

        draft = active_draft or {}
        pending_id = draft.get("pending_id") or uuid.uuid4().hex[:8]

        currency = str(
            merged.get("currency") or draft.get("currency") or context.currency or "USD"
        ).upper()
        symbol = _currency_symbol(currency)
        due_days = _parse_due_days(
            merged.get("invoice_due_days", draft.get("due_days", 30)),
            default=30,
        )
        notes = str(merged.get("invoice_notes") or draft.get("notes") or "").strip() or None

        requires_sales_tax = bool(
            merged.get("requires_sales_tax")
            if merged.get("requires_sales_tax") is not None
            else draft.get("requires_sales_tax")
            if draft.get("requires_sales_tax") is not None
            else _requires_sales_tax(context, merged)
        )

        profile = context.profile_config
        company_name = str(
            merged.get("company_name")
            or draft.get("company_name")
            or getattr(profile, "business_name", None)
            or getattr(profile, "name", None)
            or context.user_profile.get("display_name")
            or ""
        ).strip()
        company_address = str(
            merged.get("company_address")
            or draft.get("company_address")
            or getattr(profile, "address", None)
            or context.user_profile.get("company_address")
            or ""
        ).strip()
        company_phone = str(
            merged.get("company_phone")
            or draft.get("company_phone")
            or getattr(profile, "phone", None)
            or context.user_profile.get("phone")
            or ""
        ).strip()
        seller_state = str(
            merged.get("seller_state")
            or draft.get("seller_state")
            or _extract_seller_state(context, merged)
            or ""
        ).upper().strip()

        contact_name = str(merged.get("contact_name") or draft.get("contact_name") or "").strip()
        contact_email = str(merged.get("contact_email") or draft.get("contact_email") or "").strip()
        contact_phone = str(merged.get("contact_phone") or draft.get("contact_phone") or "").strip()
        buyer_line1 = str(
            merged.get("buyer_address_line1") or draft.get("buyer_address_line1") or ""
        ).strip()
        buyer_city = str(merged.get("buyer_city") or draft.get("buyer_city") or "").strip()
        buyer_state = str(
            merged.get("buyer_state") or draft.get("buyer_state") or ""
        ).strip().upper()
        buyer_postal_code = str(
            merged.get("buyer_postal_code") or draft.get("buyer_postal_code") or ""
        ).strip()
        buyer_country = str(
            merged.get("buyer_country") or draft.get("buyer_country") or "US"
        ).strip().upper()

        # Parse item hints / LLM extraction for current message
        raw_items: list[dict[str, Any]] = []
        if isinstance(draft.get("raw_items"), list):
            raw_items = list(draft["raw_items"])
        if isinstance(merged.get("invoice_items"), list):
            raw_items = merged["invoice_items"]

        if user_text and len(user_text) > 10:
            parsed = await _parse_invoice_request(user_text, currency)
            if not contact_name and parsed.get("contact_name"):
                contact_name = str(parsed["contact_name"]).strip()
            if parsed.get("items") and not merged.get("invoice_items"):
                raw_items = parsed["items"]
            if parsed.get("due_days"):
                due_days = _parse_due_days(parsed["due_days"], default=due_days)
            if parsed.get("notes") and not notes:
                notes = str(parsed["notes"]).strip() or None

        # Seller validation stage
        missing_seller_fields: list[str] = []
        if not company_name:
            missing_seller_fields.append("company_name")
        if not company_address:
            missing_seller_fields.append("company_address")
        if requires_sales_tax and not seller_state:
            missing_seller_fields.append("seller_state")
        if missing_seller_fields:
            draft_data = {
                **draft,
                "pending_id": pending_id,
                "family_id": family_id,
                "user_id": context.user_id,
                "draft_state": InvoiceDraftState.collect_seller.value,
                "contact_name": contact_name or None,
                "contact_email": contact_email or None,
                "contact_phone": contact_phone or None,
                "company_name": company_name or None,
                "company_address": company_address or None,
                "company_phone": company_phone or None,
                "seller_state": seller_state or None,
                "requires_sales_tax": requires_sales_tax,
                "due_days": due_days,
                "notes": notes,
                "currency": currency,
                "currency_symbol": symbol,
                "invoice_tax_category": str(
                    merged.get("invoice_tax_category")
                    or draft.get("invoice_tax_category")
                    or "general"
                ),
                "invoice_tax_category_code": str(
                    merged.get("invoice_tax_category_code")
                    or draft.get("invoice_tax_category_code")
                    or ""
                ),
                "buyer_address_line1": buyer_line1 or None,
                "buyer_city": buyer_city or None,
                "buyer_state": buyer_state or None,
                "buyer_postal_code": buyer_postal_code or None,
                "buyer_country": buyer_country,
                "raw_items": raw_items,
                "missing_seller_fields": missing_seller_fields,
            }
            await store_pending_invoice(pending_id, draft_data)
            return SkillResult(
                response_text=t(
                    _STRINGS,
                    "need_seller_fields",
                    lang,
                    fields=_format_missing_fields(missing_seller_fields, lang),
                )
            )

        # Buyer resolution stage
        contact: dict[str, Any] | None = None
        created_notice = ""
        buyer_candidates = (
            draft.get("buyer_candidates")
            if isinstance(draft.get("buyer_candidates"), list)
            else []
        )
        if buyer_candidates and user_text:
            chosen = _resolve_contact_name_from_candidates(user_text, buyer_candidates)
            if chosen:
                contact = chosen
                contact_name = chosen["name"]

        if not contact and draft.get("contact_id"):
            contact = await _find_contact_by_id(family_id, draft["contact_id"])

        if not contact and contact_name:
            candidates = await _find_contacts(family_id, contact_name)
            if len(candidates) == 1:
                contact = candidates[0]
            elif len(candidates) > 1:
                exact = _resolve_contact_name_from_candidates(contact_name, candidates)
                if exact:
                    contact = exact
                else:
                    options = "\n".join(f"{i + 1}. {c['name']}" for i, c in enumerate(candidates))
                    draft_data = {
                        **draft,
                        "pending_id": pending_id,
                        "family_id": family_id,
                        "user_id": context.user_id,
                        "draft_state": InvoiceDraftState.collect_buyer.value,
                        "contact_name": contact_name,
                        "contact_email": contact_email or None,
                        "contact_phone": contact_phone or None,
                        "company_name": company_name,
                        "company_address": company_address,
                        "company_phone": company_phone or None,
                        "seller_state": seller_state,
                        "requires_sales_tax": requires_sales_tax,
                        "due_days": due_days,
                        "notes": notes,
                        "currency": currency,
                        "currency_symbol": symbol,
                        "invoice_tax_category": str(
                            merged.get("invoice_tax_category")
                            or draft.get("invoice_tax_category")
                            or "general"
                        ),
                        "invoice_tax_category_code": str(
                            merged.get("invoice_tax_category_code")
                            or draft.get("invoice_tax_category_code")
                            or ""
                        ),
                        "buyer_address_line1": buyer_line1 or None,
                        "buyer_city": buyer_city or None,
                        "buyer_state": buyer_state or None,
                        "buyer_postal_code": buyer_postal_code or None,
                        "buyer_country": buyer_country,
                        "raw_items": raw_items,
                        "buyer_candidates": candidates,
                    }
                    await store_pending_invoice(pending_id, draft_data)
                    return SkillResult(
                        response_text=t(
                            _STRINGS,
                            "buyer_choices",
                            lang,
                            name=contact_name,
                            options=options,
                        )
                    )
            elif contact_email or contact_phone:
                contact = await _create_contact(
                    family_id=family_id,
                    user_id=context.user_id,
                    name=contact_name,
                    email=contact_email or None,
                    phone=contact_phone or None,
                )
                created_notice = t(_STRINGS, "buyer_created", lang, name=contact["name"])

        if not contact:
            if not contact_name:
                if draft:
                    draft_data = {
                        **draft,
                        "pending_id": pending_id,
                        "family_id": family_id,
                        "user_id": context.user_id,
                        "draft_state": InvoiceDraftState.collect_buyer.value,
                        "company_name": company_name,
                        "company_address": company_address,
                        "company_phone": company_phone or None,
                        "seller_state": seller_state,
                        "requires_sales_tax": requires_sales_tax,
                        "due_days": due_days,
                        "notes": notes,
                        "currency": currency,
                        "currency_symbol": symbol,
                        "raw_items": raw_items,
                    }
                    await store_pending_invoice(pending_id, draft_data)
                return SkillResult(response_text=t(_STRINGS, "ask_who", lang))

            missing_buyer_fields = []
            if not contact_name:
                missing_buyer_fields.append("contact_name")
            if not contact_email:
                missing_buyer_fields.append("contact_email")
            if not contact_phone:
                missing_buyer_fields.append("contact_phone")
            draft_data = {
                **draft,
                "pending_id": pending_id,
                "family_id": family_id,
                "user_id": context.user_id,
                "draft_state": InvoiceDraftState.collect_buyer.value,
                "contact_name": contact_name,
                "contact_email": contact_email or None,
                "contact_phone": contact_phone or None,
                "company_name": company_name,
                "company_address": company_address,
                "company_phone": company_phone or None,
                "seller_state": seller_state,
                "requires_sales_tax": requires_sales_tax,
                "due_days": due_days,
                "notes": notes,
                "currency": currency,
                "currency_symbol": symbol,
                "invoice_tax_category": str(
                    merged.get("invoice_tax_category")
                    or draft.get("invoice_tax_category")
                    or "general"
                ),
                "invoice_tax_category_code": str(
                    merged.get("invoice_tax_category_code")
                    or draft.get("invoice_tax_category_code")
                    or ""
                ),
                "buyer_address_line1": buyer_line1 or None,
                "buyer_city": buyer_city or None,
                "buyer_state": buyer_state or None,
                "buyer_postal_code": buyer_postal_code or None,
                "buyer_country": buyer_country,
                "raw_items": raw_items,
                "missing_buyer_fields": missing_buyer_fields,
            }
            await store_pending_invoice(pending_id, draft_data)
            return SkillResult(
                response_text=t(
                    _STRINGS,
                    "need_buyer_fields",
                    lang,
                    fields=_format_missing_fields(missing_buyer_fields, lang),
                )
            )

        # Buyer completeness for sales-tax flow
        missing_buyer_fields: list[str] = []
        if requires_sales_tax:
            if not buyer_line1:
                missing_buyer_fields.append("buyer_address_line1")
            if not buyer_city:
                missing_buyer_fields.append("buyer_city")
            if not buyer_state:
                missing_buyer_fields.append("buyer_state")
            if not buyer_postal_code:
                missing_buyer_fields.append("buyer_postal_code")
        if missing_buyer_fields:
            draft_data = {
                **draft,
                "pending_id": pending_id,
                "family_id": family_id,
                "user_id": context.user_id,
                "draft_state": InvoiceDraftState.collect_buyer.value,
                "contact_id": contact["id"],
                "contact_name": contact["name"],
                "contact_email": contact.get("email") or contact_email or None,
                "contact_phone": contact.get("phone") or contact_phone or None,
                "company_name": company_name,
                "company_address": company_address,
                "company_phone": company_phone or None,
                "seller_state": seller_state,
                "requires_sales_tax": requires_sales_tax,
                "due_days": due_days,
                "notes": notes,
                "currency": currency,
                "currency_symbol": symbol,
                "invoice_tax_category": str(
                    merged.get("invoice_tax_category")
                    or draft.get("invoice_tax_category")
                    or "general"
                ),
                "invoice_tax_category_code": str(
                    merged.get("invoice_tax_category_code")
                    or draft.get("invoice_tax_category_code")
                    or ""
                ),
                "buyer_address_line1": buyer_line1 or None,
                "buyer_city": buyer_city or None,
                "buyer_state": buyer_state or None,
                "buyer_postal_code": buyer_postal_code or None,
                "buyer_country": buyer_country,
                "raw_items": raw_items,
                "missing_buyer_fields": missing_buyer_fields,
            }
            await store_pending_invoice(pending_id, draft_data)
            return SkillResult(
                response_text=t(
                    _STRINGS,
                    "need_buyer_fields",
                    lang,
                    fields=_format_missing_fields(missing_buyer_fields, lang),
                )
            )

        # Items stage
        items = _normalize_invoice_items(raw_items)
        if not items:
            tx_items = await _pull_contact_transactions(
                family_id,
                contact,
                date_from=merged.get("date_from") or draft.get("date_from"),
                date_to=merged.get("date_to") or draft.get("date_to"),
            )
            items = tx_items
        if not items:
            draft_data = {
                **draft,
                "pending_id": pending_id,
                "family_id": family_id,
                "user_id": context.user_id,
                "draft_state": InvoiceDraftState.collect_items.value,
                "contact_id": contact["id"],
                "contact_name": contact["name"],
                "contact_email": contact.get("email") or contact_email or None,
                "contact_phone": contact.get("phone") or contact_phone or None,
                "company_name": company_name,
                "company_address": company_address,
                "company_phone": company_phone or None,
                "seller_state": seller_state,
                "requires_sales_tax": requires_sales_tax,
                "due_days": due_days,
                "notes": notes,
                "currency": currency,
                "currency_symbol": symbol,
                "invoice_tax_category": str(
                    merged.get("invoice_tax_category")
                    or draft.get("invoice_tax_category")
                    or "general"
                ),
                "invoice_tax_category_code": str(
                    merged.get("invoice_tax_category_code")
                    or draft.get("invoice_tax_category_code")
                    or ""
                ),
                "buyer_address_line1": buyer_line1 or None,
                "buyer_city": buyer_city or None,
                "buyer_state": buyer_state or None,
                "buyer_postal_code": buyer_postal_code or None,
                "buyer_country": buyer_country,
                "raw_items": raw_items,
            }
            await store_pending_invoice(pending_id, draft_data)
            return SkillResult(
                response_text=(
                    t(_STRINGS, "no_items", lang)
                    + "\n\n"
                    + t(_STRINGS, "need_item_details", lang)
                )
            )

        today = date.today()
        due = today + timedelta(days=due_days)
        invoice_number = draft.get("invoice_number") or _generate_invoice_number()
        subtotal = sum(_parse_money(item.get("amount")) for item in items)
        total = float(subtotal)

        invoice_data = {
            "pending_id": pending_id,
            "family_id": family_id,
            "user_id": context.user_id,
            "contact_id": contact["id"],
            "contact_name": contact["name"],
            "invoice_number": invoice_number,
            "invoice_date": today.isoformat(),
            "due_date": due.strftime("%B %d, %Y"),
            "due_date_iso": due.isoformat(),
            "currency": currency,
            "currency_symbol": symbol,
            "subtotal": float(subtotal),
            "tax_amount": 0.0,
            "tax_rate": 0.0,
            "tax_source": None,
            "tax_jurisdiction": None,
            "total": total,
            "items": items,
            "raw_items": raw_items,
            "notes": notes,
            "due_days": due_days,
            "company_name": company_name,
            "company_address": company_address,
            "company_phone": company_phone,
            "client_name": contact["name"],
            "client_email": contact.get("email") or contact_email,
            "client_phone": contact.get("phone") or contact_phone,
            "requires_sales_tax": requires_sales_tax,
            "invoice_tax_category": str(
                merged.get("invoice_tax_category")
                or draft.get("invoice_tax_category")
                or "general"
            ),
            "invoice_tax_category_code": str(
                merged.get("invoice_tax_category_code")
                or draft.get("invoice_tax_category_code")
                or ""
            ),
            "seller_state": seller_state,
            "buyer_address_line1": buyer_line1,
            "buyer_city": buyer_city,
            "buyer_state": buyer_state,
            "buyer_postal_code": buyer_postal_code,
            "buyer_country": buyer_country,
            "draft_state": InvoiceDraftState.await_confirm.value,
        }
        await store_pending_invoice(pending_id, invoice_data)

        preview_text = _format_preview(invoice_data, lang)
        if created_notice:
            preview_text = created_notice + "\n\n" + preview_text
        return SkillResult(
            response_text=preview_text,
            buttons=[
                {
                    "text": t(_STRINGS, "btn_confirm", lang),
                    "callback": f"invoice_confirm:{pending_id}",
                },
                {
                    "text": t(_STRINGS, "btn_edit", lang),
                    "callback": f"invoice_edit:{pending_id}",
                },
                {
                    "text": t(_STRINGS, "btn_cancel", lang),
                    "callback": f"invoice_cancel:{pending_id}",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        return GENERATE_INVOICE_SYSTEM_PROMPT.format(
            timezone=context.timezone,
            now_local=now_local.strftime("%Y-%m-%d %H:%M"),
        )


# ---------------------------------------------------------------------------
# PDF generation (called from router callback)
# ---------------------------------------------------------------------------
async def generate_invoice_pdf(invoice_data: dict) -> bytes:
    """Render invoice HTML → PDF via WeasyPrint in a thread."""
    import asyncio

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape(default=True))
    template = env.from_string(INVOICE_HTML_TEMPLATE)
    html = template.render(
        company_name=invoice_data["company_name"],
        company_address=invoice_data.get("company_address", ""),
        company_phone=invoice_data.get("company_phone", ""),
        invoice_number=invoice_data["invoice_number"],
        invoice_date=invoice_data["invoice_date"],
        due_date=invoice_data["due_date"],
        client_name=invoice_data["client_name"],
        client_email=invoice_data.get("client_email", ""),
        client_phone=invoice_data.get("client_phone", ""),
        currency=invoice_data["currency"],
        currency_symbol=invoice_data["currency_symbol"],
        items=invoice_data["items"],
        subtotal=invoice_data.get("subtotal", invoice_data.get("total", 0)),
        tax_amount=invoice_data.get("tax_amount", 0),
        tax_rate=invoice_data.get("tax_rate", 0),
        total=invoice_data["total"],
        notes=invoice_data.get("notes") or "Payment due upon receipt.",
    )

    from weasyprint import HTML

    return await asyncio.to_thread(HTML(string=html).write_pdf)


async def save_invoice_to_db(invoice_data: dict, document_id: uuid.UUID | None = None) -> Invoice:
    """Persist Invoice record to database."""
    invoice = Invoice(
        id=uuid.uuid4(),
        family_id=uuid.UUID(invoice_data["family_id"]),
        user_id=uuid.UUID(invoice_data["user_id"]),
        contact_id=(
            uuid.UUID(invoice_data["contact_id"]) if invoice_data.get("contact_id") else None
        ),
        invoice_number=invoice_data["invoice_number"],
        status=InvoiceStatus.draft,
        invoice_date=date.fromisoformat(invoice_data["invoice_date"]),
        due_date=date.fromisoformat(invoice_data["due_date_iso"]),
        currency=invoice_data["currency"],
        subtotal=invoice_data.get("subtotal"),
        tax_amount=invoice_data.get("tax_amount", 0),
        tax_rate=invoice_data.get("tax_rate", 0),
        tax_source=invoice_data.get("tax_source"),
        tax_jurisdiction=invoice_data.get("tax_jurisdiction"),
        total=invoice_data["total"],
        items=invoice_data["items"],
        notes=invoice_data.get("notes"),
        company_name=invoice_data.get("company_name"),
        company_address=invoice_data.get("company_address"),
        company_phone=invoice_data.get("company_phone"),
        client_name=invoice_data["client_name"],
        client_email=invoice_data.get("client_email"),
        client_phone=invoice_data.get("client_phone"),
        document_id=document_id,
    )

    async with async_session() as session:
        session.add(invoice)
        await session.commit()

    return invoice


skill = GenerateInvoiceSkill()
