"""Generate invoice skill — create PDF invoices from contacts and transactions.

Invoicing specialist: builds invoices using contact info and recent transactions,
generates a PDF document for sending to clients.
"""

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.contact import Contact
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

INVOICE_SYSTEM_PROMPT = """\
You are an invoicing assistant. Generate a clear, professional invoice summary.
You receive transaction data and contact info from SQL.
Format the invoice as a clean HTML summary for the user to review before sending.
Include: contact name, line items, amounts, total, suggested due date (net 30).
Use <b>bold</b> for totals. Keep it scannable."""


register_strings("generate_invoice", {"en": {}, "ru": {}, "es": {}})


class GenerateInvoiceSkill:
    name = "generate_invoice"
    intents = ["generate_invoice"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        return INVOICE_SYSTEM_PROMPT

    @observe(name="skill_generate_invoice")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        family_id = context.family_id
        if not family_id:
            return SkillResult(
                response_text="Set up your account first to generate invoices."
            )

        contact_name = intent_data.get("contact_name")
        if not contact_name:
            return SkillResult(
                response_text="Who should I invoice? "
                "Try: \"invoice Mike Chen for the bathroom job\""
            )

        # Find contact
        contact = await self._find_contact(family_id, contact_name)
        if not contact:
            return SkillResult(
                response_text=f"I don't have {contact_name}'s info. "
                f"Want to add them first? Try: \"add contact {contact_name}\""
            )

        # Find recent transactions (last 30 days) as potential line items
        transactions = await self._get_recent_transactions(
            family_id, days=30
        )

        # Build invoice context for LLM
        today = date.today()
        due_date = today + timedelta(days=30)

        data_lines = [
            f"Invoice date: {today.isoformat()}",
            f"Due date: {due_date.isoformat()}",
            f"Currency: {context.currency}",
            f"\nClient: {contact['name']}",
        ]
        if contact.get("email"):
            data_lines.append(f"Email: {contact['email']}")
        if contact.get("phone"):
            data_lines.append(f"Phone: {contact['phone']}")

        if transactions:
            data_lines.append(f"\nRecent transactions ({len(transactions)}):")
            total = 0.0
            for tx in transactions:
                data_lines.append(
                    f"  {tx['date']} — {tx['description']} — "
                    f"{tx['amount']:.2f} {context.currency}"
                )
                total += tx["amount"]
            data_lines.append(f"\nTotal from transactions: {total:.2f}")
        else:
            data_lines.append("\nNo recent transactions found.")

        data_text = "\n".join(data_lines)

        # LLM generates the invoice summary
        assembled = intent_data.get("_assembled")
        model = intent_data.get("_model", self.model)
        response = await generate_text(
            model=model,
            system_prompt=INVOICE_SYSTEM_PROMPT,
            user_message=(
                f"{message.text}\n\n--- DATA ---\n{data_text}\n\n"
                "Generate a clean invoice summary the user can review. "
                "Ask if they want to send it as PDF."
            ),
            assembled_context=assembled,
        )

        return SkillResult(response_text=response)

    @staticmethod
    async def _find_contact(
        family_id: str, name: str,
    ) -> dict[str, Any] | None:
        """Find a contact by name (fuzzy match)."""
        async with async_session() as session:
            stmt = (
                select(Contact)
                .where(
                    Contact.family_id == uuid.UUID(family_id),
                    Contact.name.ilike(f"%{name}%"),
                )
                .limit(1)
            )
            result = await session.scalar(stmt)
            if not result:
                return None
            return {
                "name": result.name,
                "email": result.email,
                "phone": result.phone,
                "id": str(result.id),
            }

    @staticmethod
    async def _get_recent_transactions(
        family_id: str, days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get recent income transactions as potential invoice items."""
        cutoff = date.today() - timedelta(days=days)
        async with async_session() as session:
            stmt = (
                select(Transaction)
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.income,
                    Transaction.date >= cutoff,
                )
                .order_by(Transaction.date.desc())
                .limit(20)
            )
            rows = (await session.scalars(stmt)).all()
            return [
                {
                    "date": r.date.isoformat(),
                    "description": r.merchant or r.description or "Service",
                    "amount": float(r.amount),
                }
                for r in rows
            ]


skill = GenerateInvoiceSkill()
