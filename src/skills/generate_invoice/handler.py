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
import uuid
from datetime import date, timedelta
from typing import Any

from jinja2 import BaseLoader, Environment
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
        "no_contact": (
            "I don't have <b>{name}</b> in your contacts. "
            'Add them first: "add contact {name}"'
        ),
        "no_items": (
            "No items to invoice. Tell me what to include:\n"
            '• "invoice Mike for plumbing $500, parts $150"\n'
            '• "invoice Sarah for this month\'s work"'
        ),
        "preview_header": "📋 <b>Invoice Preview #{number}</b>",
        "preview_client": "Client: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Total: {symbol}{total}</b>",
        "preview_due": "Due: {date}",
        "preview_notes": "Notes: {notes}",
        "btn_confirm": "✅ Generate PDF",
        "btn_edit": "✏️ Edit",
        "btn_cancel": "❌ Cancel",
        "expired": "Invoice preview expired. Please try again.",
        "cancelled": "Invoice cancelled.",
        "generated": (
            "📄 <b>Invoice #{number}</b>\n"
            "Client: {name}\n"
            "Total: {symbol}{total}\n"
            "Due: {due}"
        ),
        "pdf_failed": "Failed to generate PDF. Please try again.",
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
        "no_contact": (
            "Контакт <b>{name}</b> не найден. "
            'Сначала добавьте: "добавь контакт {name}"'
        ),
        "no_items": (
            "Нет позиций для инвойса. Укажите что включить:\n"
            '• "инвойс Mike за ремонт $500, запчасти $150"\n'
            '• "инвойс Sarah за работу в этом месяце"'
        ),
        "preview_header": "📋 <b>Предпросмотр инвойса #{number}</b>",
        "preview_client": "Клиент: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Итого: {symbol}{total}</b>",
        "preview_due": "Оплатить до: {date}",
        "preview_notes": "Примечание: {notes}",
        "btn_confirm": "✅ Создать PDF",
        "btn_edit": "✏️ Изменить",
        "btn_cancel": "❌ Отменить",
        "expired": "Предпросмотр истёк. Попробуйте снова.",
        "cancelled": "Инвойс отменён.",
        "generated": (
            "📄 <b>Инвойс #{number}</b>\n"
            "Клиент: {name}\n"
            "Итого: {symbol}{total}\n"
            "Оплатить до: {due}"
        ),
        "pdf_failed": "Не удалось создать PDF. Попробуйте снова.",
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
        "no_contact": (
            "No tengo a <b>{name}</b> en tus contactos. "
            'Agrégalo primero: "agregar contacto {name}"'
        ),
        "no_items": (
            "No hay elementos para facturar. Dime qué incluir:\n"
            '• "factura Mike por plomería $500, materiales $150"\n'
            '• "factura Sarah por el trabajo de este mes"'
        ),
        "preview_header": "📋 <b>Vista previa de factura #{number}</b>",
        "preview_client": "Cliente: {name}",
        "preview_email": "  ✉️ {email}",
        "preview_total": "\n<b>Total: {symbol}{total}</b>",
        "preview_due": "Vencimiento: {date}",
        "preview_notes": "Notas: {notes}",
        "btn_confirm": "✅ Generar PDF",
        "btn_edit": "✏️ Editar",
        "btn_cancel": "❌ Cancelar",
        "expired": "La vista previa expiró. Inténtalo de nuevo.",
        "cancelled": "Factura cancelada.",
        "generated": (
            "📄 <b>Factura #{number}</b>\n"
            "Cliente: {name}\n"
            "Total: {symbol}{total}\n"
            "Vencimiento: {due}"
        ),
        "pdf_failed": "No se pudo generar el PDF. Inténtalo de nuevo.",
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
        <td colspan="4"><b>Total</b></td>
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
    await redis.set(
        f"invoice_pending:{pending_id}",
        json.dumps(data, default=str),
        ex=PENDING_INVOICE_TTL,
    )


async def get_pending_invoice(pending_id: str) -> dict | None:
    raw = await redis.get(f"invoice_pending:{pending_id}")
    if not raw:
        return None
    return json.loads(raw)


async def delete_pending_invoice(pending_id: str) -> None:
    await redis.delete(f"invoice_pending:{pending_id}")


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


async def _find_contact(family_id: str, name: str) -> dict[str, Any] | None:
    """Find contact by name (fuzzy word match)."""
    async with async_session() as session:
        words = split_search_words(name)
        name_filter = (
            ilike_all_words(Contact.name, words) if words else Contact.name.ilike(f"%{name}%")
        )
        stmt = (
            select(Contact)
            .where(Contact.family_id == uuid.UUID(family_id), name_filter)
            .limit(1)
        )
        result = await session.scalar(stmt)
        if not result:
            return None
        return {
            "id": str(result.id),
            "name": result.name,
            "email": result.email,
            "phone": result.phone,
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

        currency = context.currency or "USD"
        symbol = _currency_symbol(currency)
        user_text = message.text or ""

        # 1. Get contact name from intent or LLM extraction
        contact_name = intent_data.get("contact_name")
        parsed_items: list[dict] = []
        due_days = intent_data.get("invoice_due_days") or 30
        notes = intent_data.get("invoice_notes")

        # Try LLM extraction if we have user text with potential items
        if user_text and len(user_text) > 10:
            parsed = await _parse_invoice_request(user_text, currency)
            if not contact_name and parsed.get("contact_name"):
                contact_name = parsed["contact_name"]
            if parsed.get("items"):
                parsed_items = parsed["items"]
            if parsed.get("due_days"):
                due_days = parsed["due_days"]
            if parsed.get("notes") and not notes:
                notes = parsed["notes"]

        # Also check intent_data for pre-extracted items
        if intent_data.get("invoice_items"):
            parsed_items = intent_data["invoice_items"]

        if not contact_name:
            return SkillResult(response_text=t(_STRINGS, "ask_who", lang))

        # 2. Resolve contact from DB
        contact = await _find_contact(family_id, contact_name)
        if not contact:
            return SkillResult(
                response_text=t(_STRINGS, "no_contact", lang, name=contact_name)
            )

        # 3. Build line items
        items: list[dict] = []

        # a) From parsed user text
        for pi in parsed_items:
            qty = pi.get("quantity", 1)
            unit_price = pi.get("unit_price", pi.get("amount", 0))
            items.append({
                "description": pi["description"],
                "quantity": qty,
                "unit_price": unit_price,
                "amount": round(qty * unit_price, 2),
            })

        # b) From DB transactions (only if no explicit items)
        if not items:
            tx_items = await _pull_contact_transactions(
                family_id,
                contact,
                date_from=intent_data.get("date_from"),
                date_to=intent_data.get("date_to"),
            )
            items = tx_items

        # 4. If still nothing — ask for info
        if not items:
            return SkillResult(response_text=t(_STRINGS, "no_items", lang))

        # 5. Build invoice data
        today = date.today()
        due = today + timedelta(days=int(due_days))
        invoice_number = _generate_invoice_number()
        total = sum(item.get("amount", 0) for item in items)

        # Company info from profile
        profile = context.profile_config
        company_name = "My Business"
        company_address = ""
        company_phone = ""
        if profile:
            company_name = getattr(profile, "business_name", None) or company_name
            company_address = getattr(profile, "address", None) or ""
            company_phone = getattr(profile, "phone", None) or ""

        invoice_data = {
            "family_id": family_id,
            "user_id": context.user_id,
            "contact_id": contact["id"],
            "invoice_number": invoice_number,
            "invoice_date": today.isoformat(),
            "due_date": due.strftime("%B %d, %Y"),
            "due_date_iso": due.isoformat(),
            "currency": currency,
            "currency_symbol": symbol,
            "total": total,
            "items": items,
            "notes": notes,
            "company_name": company_name,
            "company_address": company_address,
            "company_phone": company_phone,
            "client_name": contact["name"],
            "client_email": contact.get("email"),
            "client_phone": contact.get("phone"),
        }

        # 6. Store in Redis, show preview with confirm/edit/cancel buttons
        pending_id = uuid.uuid4().hex[:8]
        await store_pending_invoice(pending_id, invoice_data)

        preview_text = _format_preview(invoice_data, lang)
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

    env = Environment(loader=BaseLoader())
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
