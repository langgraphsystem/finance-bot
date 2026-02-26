"""Tests for GenerateInvoiceSkill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_invoice.handler import skill


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


def _mock_contact(name="Mike Chen", email="mike@test.com", phone="555-1234"):
    """Create a mock Contact ORM object."""
    import uuid

    contact = MagicMock()
    contact.name = name
    contact.email = email
    contact.phone = phone
    contact.id = uuid.uuid4()
    return contact


def _mock_transaction(date_str, description, amount):
    """Create a mock Transaction ORM object."""
    from datetime import date

    tx = MagicMock()
    tx.date = date.fromisoformat(date_str)
    tx.merchant = description
    tx.description = description
    tx.amount = amount
    return tx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_skill_attributes():
    """Skill has required attributes."""
    assert skill.name == "generate_invoice"
    assert "generate_invoice" in skill.intents


async def test_no_family_id():
    """Returns setup message when no family_id."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id=None, role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    message = _make_message("invoice Mike")
    result = await skill.execute(message, ctx, {})
    assert "set up" in result.response_text.lower()


async def test_no_contact_name():
    """Returns help message when no contact name provided."""
    message = _make_message("create invoice")
    intent_data = {}

    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id="fam-123", role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    result = await skill.execute(message, ctx, intent_data)
    assert "who should i invoice" in result.response_text.lower()


async def test_contact_not_found(sample_context):
    """Returns message when contact not found."""
    message = _make_message("invoice John Doe")
    intent_data = {"contact_name": "John Doe"}

    mock_sess = AsyncMock()
    mock_sess.scalar = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.skills.generate_invoice.handler.async_session",
        return_value=ctx,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    assert "don't have" in result.response_text.lower()
    assert "John Doe" in result.response_text


async def test_invoice_generated_with_contact(sample_context):
    """Invoice is generated when contact and transactions exist."""
    message = _make_message("invoice Mike Chen for plumbing work")
    intent_data = {"contact_name": "Mike Chen"}

    contact = _mock_contact()
    transactions = [
        _mock_transaction("2026-02-20", "Plumbing repair", 500.0),
        _mock_transaction("2026-02-15", "Parts", 150.0),
    ]

    # Mock for _find_contact (scalar returns contact)
    mock_sess_contact = AsyncMock()
    mock_sess_contact.scalar = AsyncMock(return_value=contact)
    ctx_contact = MagicMock()
    ctx_contact.__aenter__ = AsyncMock(return_value=mock_sess_contact)
    ctx_contact.__aexit__ = AsyncMock(return_value=False)

    # Mock for _get_recent_transactions (scalars returns list)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = transactions
    mock_sess_tx = AsyncMock()
    mock_sess_tx.scalars = AsyncMock(return_value=mock_scalars)
    ctx_tx = MagicMock()
    ctx_tx.__aenter__ = AsyncMock(return_value=mock_sess_tx)
    ctx_tx.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ctx_contact
        return ctx_tx

    with (
        patch(
            "src.skills.generate_invoice.handler.async_session",
            side_effect=session_factory,
        ),
        patch(
            "src.skills.generate_invoice.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Invoice for Mike Chen</b>\nPlumbing: $500\nParts: $150\nTotal: $650",
        ) as mock_llm,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()
    assert result.response_text is not None


async def test_invoice_no_transactions(sample_context):
    """Invoice still generated when contact exists but no transactions."""
    message = _make_message("invoice Sarah")
    intent_data = {"contact_name": "Sarah"}

    contact = _mock_contact(name="Sarah", email="sarah@test.com")

    mock_sess_contact = AsyncMock()
    mock_sess_contact.scalar = AsyncMock(return_value=contact)
    ctx_contact = MagicMock()
    ctx_contact.__aenter__ = AsyncMock(return_value=mock_sess_contact)
    ctx_contact.__aexit__ = AsyncMock(return_value=False)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_sess_tx = AsyncMock()
    mock_sess_tx.scalars = AsyncMock(return_value=mock_scalars)
    ctx_tx = MagicMock()
    ctx_tx.__aenter__ = AsyncMock(return_value=mock_sess_tx)
    ctx_tx.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ctx_contact
        return ctx_tx

    with (
        patch(
            "src.skills.generate_invoice.handler.async_session",
            side_effect=session_factory,
        ),
        patch(
            "src.skills.generate_invoice.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Invoice for Sarah — no recent transactions to include.",
        ) as mock_llm,
    ):
        await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()
