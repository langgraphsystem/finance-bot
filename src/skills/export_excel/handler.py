"""Excel export skill — generate .xlsx spreadsheets from user data.

Supports three export types:
- expenses: Transactions with summary sheet + category breakdown
- tasks: Task list with status and due dates
- contacts: Contact list with phone/email
"""

import io
import logging
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You help the user export data as an Excel spreadsheet.
Respond in: {language}."""


def _parse_date_range(
    intent_data: dict[str, Any],
) -> tuple[date, date]:
    """Extract date range from intent_data. Defaults to current month."""
    today = date.today()
    period = intent_data.get("period", "month")
    date_from = intent_data.get("date_from")
    date_to = intent_data.get("date_to")

    if date_from and date_to:
        try:
            return date.fromisoformat(date_from), date.fromisoformat(date_to)
        except (ValueError, TypeError):
            pass

    if period == "week":
        return today - timedelta(days=7), today
    if period == "year":
        return date(today.year, 1, 1), today
    # Default: current month
    return date(today.year, today.month, 1), today


def _detect_export_type(intent_data: dict[str, Any], message_text: str) -> str:
    """Determine what to export from intent_data or message text."""
    export_type = intent_data.get("export_type")
    if export_type in ("expenses", "tasks", "contacts"):
        return export_type

    lower = (message_text or "").lower()
    if any(w in lower for w in ("task", "задач", "todo", "дела")):
        return "tasks"
    if any(w in lower for w in ("contact", "контакт", "client", "клиент")):
        return "contacts"
    return "expenses"


class ExportExcelSkill:
    name = "export_excel"
    intents = ["export_excel"]
    model = "claude-haiku-4-5"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="export_excel")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        export_type = _detect_export_type(intent_data, message.text or "")

        try:
            if export_type == "tasks":
                xlsx_bytes, filename = await self._export_tasks(context)
            elif export_type == "contacts":
                xlsx_bytes, filename = await self._export_contacts(context)
            else:
                date_from, date_to = _parse_date_range(intent_data)
                xlsx_bytes, filename = await self._export_expenses(
                    context, date_from, date_to
                )

            if not xlsx_bytes:
                return SkillResult(
                    response_text="No data found for the requested export."
                )

            return SkillResult(
                response_text=f"Here's your {export_type} export:",
                document=xlsx_bytes,
                document_name=filename,
            )
        except Exception as e:
            logger.error("Excel export failed: %s", e, exc_info=True)
            return SkillResult(
                response_text="Export failed. Please try again later."
            )

    async def _export_expenses(
        self,
        ctx: SessionContext,
        date_from: date,
        date_to: date,
    ) -> tuple[bytes, str]:
        """Generate expenses Excel with Summary + Transactions sheets."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        async with async_session() as session:
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= date_from,
                    Transaction.date <= date_to,
                    Transaction.type == TransactionType.expense,
                )
                .order_by(Transaction.date.desc())
                .limit(10000)
            )
            transactions = list(result.scalars().all())

        if not transactions:
            return b"", ""

        wb = Workbook()

        # --- Transactions sheet ---
        ws = wb.active
        ws.title = "Transactions"
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="DAEEF3", fill_type="solid")
        headers = ["Date", "Merchant", "Category", "Amount", "Description"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        for row, tx in enumerate(transactions, 2):
            ws.cell(row=row, column=1, value=str(tx.date) if tx.date else "")
            ws.cell(row=row, column=2, value=tx.merchant or "")
            ws.cell(row=row, column=3, value=tx.category or "")
            ws.cell(row=row, column=4, value=float(tx.amount))
            ws.cell(row=row, column=5, value=tx.description or "")

        # Auto-fit column widths
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value) if cell.value else ""
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

        # --- Summary sheet ---
        ws_sum = wb.create_sheet("Summary")
        ws_sum.cell(row=1, column=1, value="Period").font = header_font
        ws_sum.cell(
            row=1,
            column=2,
            value=f"{date_from.isoformat()} to {date_to.isoformat()}",
        )

        total = sum(float(tx.amount) for tx in transactions)
        ws_sum.cell(row=2, column=1, value="Total Expenses").font = header_font
        ws_sum.cell(row=2, column=2, value=total)
        ws_sum.cell(row=3, column=1, value="Transactions").font = header_font
        ws_sum.cell(row=3, column=2, value=len(transactions))

        # Category breakdown
        cat_totals: dict[str, float] = {}
        for tx in transactions:
            cat = tx.category or "Other"
            cat_totals[cat] = cat_totals.get(cat, 0) + float(tx.amount)

        ws_sum.cell(row=5, column=1, value="Category").font = header_font
        ws_sum.cell(row=5, column=1).fill = header_fill
        ws_sum.cell(row=5, column=2, value="Amount").font = header_font
        ws_sum.cell(row=5, column=2).fill = header_fill

        for i, (cat, amt) in enumerate(
            sorted(cat_totals.items(), key=lambda x: -x[1]), 6
        ):
            ws_sum.cell(row=i, column=1, value=cat)
            ws_sum.cell(row=i, column=2, value=amt)

        ws_sum.column_dimensions["A"].width = 20
        ws_sum.column_dimensions["B"].width = 15

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"expenses_{date_from.isoformat()}_{date_to.isoformat()}.xlsx"
        return buf.read(), filename

    async def _export_tasks(self, ctx: SessionContext) -> tuple[bytes, str]:
        """Generate tasks Excel."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        from src.core.models.task import Task

        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                )
                .order_by(Task.created_at.desc())
                .limit(1000)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return b"", ""

        wb = Workbook()
        ws = wb.active
        ws.title = "Tasks"
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="DAEEF3", fill_type="solid")
        headers = ["Title", "Status", "Due Date", "Created", "Description"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        for row, t in enumerate(tasks, 2):
            ws.cell(row=row, column=1, value=t.title or "")
            ws.cell(
                row=row,
                column=2,
                value=t.status.value if hasattr(t.status, "value") else str(t.status),
            )
            ws.cell(row=row, column=3, value=str(t.due_at) if t.due_at else "")
            ws.cell(
                row=row,
                column=4,
                value=str(t.created_at) if t.created_at else "",
            )
            ws.cell(row=row, column=5, value=t.description or "")

        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value) if cell.value else ""
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.read(), "tasks.xlsx"

    async def _export_contacts(self, ctx: SessionContext) -> tuple[bytes, str]:
        """Generate contacts Excel."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        from src.core.models.contact import Contact

        async with async_session() as session:
            result = await session.execute(
                select(Contact)
                .where(Contact.family_id == uuid.UUID(ctx.family_id))
                .order_by(Contact.name.asc())
                .limit(1000)
            )
            contacts = list(result.scalars().all())

        if not contacts:
            return b"", ""

        wb = Workbook()
        ws = wb.active
        ws.title = "Contacts"
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="DAEEF3", fill_type="solid")
        headers = ["Name", "Phone", "Email", "Role", "Notes"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill

        for row, c in enumerate(contacts, 2):
            ws.cell(row=row, column=1, value=c.name or "")
            ws.cell(row=row, column=2, value=c.phone or "")
            ws.cell(row=row, column=3, value=c.email or "")
            ws.cell(row=row, column=4, value=c.role or "")
            ws.cell(row=row, column=5, value=c.notes or "")

        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value) if cell.value else ""
                max_len = max(max_len, len(val))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.read(), "contacts.xlsx"


skill = ExportExcelSkill()
