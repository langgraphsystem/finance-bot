"""Tests for generate_invoice_pdf skill."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# Pre-inject a fake weasyprint module so the real one (needing GTK) is never loaded
_fake_weasyprint = types.ModuleType("weasyprint")
_fake_weasyprint.HTML = MagicMock()
sys.modules.setdefault("weasyprint", _fake_weasyprint)

from src.skills.generate_invoice_pdf.handler import skill  # noqa: E402


async def test_generate_invoice_no_family(sample_context, text_message):
    """Requires account setup."""
    sample_context.family_id = None
    result = await skill.execute(text_message, sample_context, {})
    assert "Set up" in result.response_text or "настройте" in result.response_text.lower()


async def test_generate_invoice_no_contact(sample_context, text_message):
    """Asks who to invoice."""
    result = await skill.execute(text_message, sample_context, {})
    txt = result.response_text
    assert "Who should I invoice" in txt or "Кому выставить" in txt


async def test_generate_invoice_contact_not_found(sample_context, text_message):
    """Reports when contact not found."""
    with patch.object(skill, "_find_contact", new_callable=AsyncMock, return_value=None):
        result = await skill.execute(
            text_message, sample_context, {"contact_name": "Unknown Person"}
        )
        assert "don't have" in result.response_text or "нет данных" in result.response_text.lower()


async def test_generate_invoice_no_transactions(sample_context, text_message):
    """Reports when no transactions to invoice."""
    contact = {"name": "Mike Chen", "email": "mike@test.com", "phone": "555-1234"}
    with (
        patch.object(skill, "_find_contact", new_callable=AsyncMock, return_value=contact),
        patch.object(
            skill,
            "_get_recent_transactions",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await skill.execute(text_message, sample_context, {"contact_name": "Mike"})
        text = result.response_text
        assert "No recent transactions" in text or "Нет недавних транзакций" in text


async def test_generate_invoice_success(sample_context, text_message):
    """Generates PDF invoice successfully."""
    contact = {"name": "Mike Chen", "email": "mike@test.com", "phone": "555-1234"}
    transactions = [
        {"date": "2026-02-15", "description": "Plumbing repair", "amount": 250.0},
        {"date": "2026-02-20", "description": "Pipe installation", "amount": 500.0},
    ]

    with (
        patch.object(skill, "_find_contact", new_callable=AsyncMock, return_value=contact),
        patch.object(
            skill,
            "_get_recent_transactions",
            new_callable=AsyncMock,
            return_value=transactions,
        ),
    ):
        mock_html = MagicMock()
        mock_html.return_value.write_pdf.return_value = b"%PDF-fake"
        sys.modules["weasyprint"].HTML = mock_html

        result = await skill.execute(text_message, sample_context, {"contact_name": "Mike"})
        assert "Invoice" in result.response_text or "Инвойс" in result.response_text
        assert "Mike Chen" in result.response_text
        assert "750.00" in result.response_text
        assert result.document is not None
        assert result.document_name.endswith(".pdf")


async def test_skill_attributes():
    assert skill.name == "generate_invoice_pdf"
    assert "generate_invoice_pdf" in skill.intents
    assert skill.model == "claude-sonnet-4-6"
