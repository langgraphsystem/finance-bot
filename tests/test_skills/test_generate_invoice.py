"""Tests for unified GenerateInvoiceSkill (preview → confirm → PDF)."""

import json
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.generate_invoice.handler import (
    _format_preview,
    _generate_invoice_number,
    _resolve_contact_name_from_candidates,
    delete_pending_invoice,
    get_pending_invoice,
    is_pending_invoice_owner,
    skill,
    store_pending_invoice,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


def _make_context(
    lang="en", currency="USD", family_id=None, business_type="plumber", with_profile=True,
) -> SessionContext:
    profile = None
    if with_profile:
        profile = SimpleNamespace(
            business_name="Test Seller LLC",
            address="10 Market Street",
            phone="555-0000",
            tax={},
        )
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=family_id or str(uuid.uuid4()),
        role="owner",
        language=lang,
        currency=currency,
        business_type=business_type,
        categories=[],
        merchant_mappings=[],
        profile_config=profile,
    )


def _mock_contact(
    name="Mike Chen", email="mike@test.com", phone="555-1234",
):
    contact = MagicMock()
    contact.name = name
    contact.email = email
    contact.phone = phone
    contact.id = uuid.uuid4()
    return contact


def _mock_transaction(date_str, description, amount, contact_id=None):
    tx = MagicMock()
    tx.date = date.fromisoformat(date_str)
    tx.merchant = description
    tx.description = description
    tx.amount = amount
    tx.id = uuid.uuid4()
    tx.contact_id = contact_id
    return tx


_UNSET = object()


def _mock_async_session(scalar_value=_UNSET, scalars_list=None):
    """Create a mock async session context manager.

    Use scalar_value for single-object queries (_find_contact),
    scalars_list for multi-row queries (_pull_contact_transactions).
    """
    mock_sess = AsyncMock()
    if scalar_value is not _UNSET:
        mock_sess.scalar = AsyncMock(return_value=scalar_value)
    if scalars_list is None and scalar_value is not _UNSET:
        scalars_list = [scalar_value] if scalar_value is not None else []
    if scalars_list is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_list
        mock_sess.scalars = AsyncMock(return_value=mock_scalars)
        mock_sess.execute = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Basic attribute tests
# ---------------------------------------------------------------------------

async def test_skill_attributes():
    assert skill.name == "generate_invoice"
    assert "generate_invoice" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


async def test_get_system_prompt():
    ctx = _make_context()
    prompt = skill.get_system_prompt(ctx)
    assert "invoice" in prompt.lower()


# ---------------------------------------------------------------------------
# No family / no contact
# ---------------------------------------------------------------------------

async def test_no_family_id():
    ctx = SessionContext(
        user_id="u1", family_id=None, role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    msg = _make_message("invoice Mike")
    with patch(
        "src.skills.generate_invoice.handler._parse_invoice_request",
        new_callable=AsyncMock,
        return_value={"contact_name": "Mike", "items": [], "due_days": 30, "notes": None},
    ):
        result = await skill.execute(msg, ctx, {})
    assert "account" in result.response_text.lower() or "аккаунт" in result.response_text.lower()


async def test_no_contact_name_asks():
    """Returns help when no contact name can be determined."""
    ctx = _make_context()
    msg = _make_message("invoice")
    with patch(
        "src.skills.generate_invoice.handler._parse_invoice_request",
        new_callable=AsyncMock,
        return_value={"contact_name": None, "items": [], "due_days": 30, "notes": None},
    ):
        result = await skill.execute(msg, ctx, {})
    assert "who" in result.response_text.lower() or "кому" in result.response_text.lower()


async def test_contact_not_found():
    ctx = _make_context()
    msg = _make_message("invoice John Doe for work")
    intent_data = {"contact_name": "John Doe"}

    contact_sess = _mock_async_session(scalar_value=None)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={"contact_name": "John Doe", "items": [], "due_days": 30, "notes": None},
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    text_lower = result.response_text.lower()
    assert "buyer" in text_lower or "покупател" in text_lower


# ---------------------------------------------------------------------------
# Explicit items from user text (LLM extraction)
# ---------------------------------------------------------------------------

async def test_explicit_items_from_text():
    """LLM parses items from user text → preview with buttons."""
    ctx = _make_context()
    msg = _make_message("invoice Mike Chen for plumbing repair $500 and pipe installation $150")
    intent_data = {"contact_name": "Mike Chen"}
    contact = _mock_contact()

    contact_sess = _mock_async_session(scalar_value=contact)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike Chen",
                "items": [
                    {"description": "Plumbing repair", "quantity": 1, "unit_price": 500.0},
                    {"description": "Pipe installation", "quantity": 1, "unit_price": 150.0},
                ],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, intent_data)

    # Should show preview with totals
    assert "650.00" in result.response_text
    assert "Mike Chen" in result.response_text
    # Should have 3 buttons (confirm, edit, cancel) — no PDF yet
    assert result.buttons is not None
    assert len(result.buttons) == 3
    assert result.document is None
    # Redis store called
    mock_store.assert_called_once()


# ---------------------------------------------------------------------------
# Contact with DB transactions
# ---------------------------------------------------------------------------

async def test_contact_with_transactions():
    """Pulls DB transactions when no explicit items."""
    ctx = _make_context()
    msg = _make_message("invoice Sarah for this month's work")
    intent_data = {"contact_name": "Sarah"}
    contact = _mock_contact(name="Sarah", email="sarah@test.com")
    contact_id = contact.id
    txns = [
        _mock_transaction("2026-02-10", "Web design", 1200.0, contact_id),
        _mock_transaction("2026-02-18", "Logo revision", 300.0, contact_id),
    ]

    contact_sess = _mock_async_session(scalar_value=contact)
    tx_sess = _mock_async_session(scalars_list=txns)
    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        return contact_sess if call_count == 1 else tx_sess

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Sarah",
                "items": [],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            side_effect=session_factory,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, intent_data)

    assert "Sarah" in result.response_text
    assert "1500.00" in result.response_text or "1,500" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 3
    assert result.document is None
    mock_store.assert_called_once()


# ---------------------------------------------------------------------------
# No items and no transactions → asks
# ---------------------------------------------------------------------------

async def test_contact_no_transactions_no_fallback():
    """Returns 'no items' message when contact exists but no transactions."""
    ctx = _make_context()
    msg = _make_message("invoice Bob")
    intent_data = {"contact_name": "Bob"}
    contact = _mock_contact(name="Bob")

    contact_sess = _mock_async_session(scalar_value=contact)
    empty_tx_sess = _mock_async_session(scalars_list=[])
    # Need two calls for the two queries in _pull_contact_transactions
    empty_tx_sess2 = _mock_async_session(scalars_list=[])
    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return contact_sess
        if call_count == 2:
            return empty_tx_sess
        return empty_tx_sess2

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Bob",
                "items": [],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            side_effect=session_factory,
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    text_lower = result.response_text.lower()
    assert "no items" in text_lower or "нет позиций" in text_lower
    assert result.buttons is None


# ---------------------------------------------------------------------------
# Custom due days
# ---------------------------------------------------------------------------

async def test_custom_due_days():
    """Respects invoice_due_days from intent_data."""
    ctx = _make_context()
    msg = _make_message("invoice Mike net 15")
    intent_data = {"contact_name": "Mike", "invoice_due_days": 15}
    contact = _mock_contact(name="Mike")
    contact_sess = _mock_async_session(scalar_value=contact)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [
                    {"description": "Work", "quantity": 1, "unit_price": 100.0},
                ],
                "due_days": 15,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, intent_data)

    # Verify preview returned with buttons
    assert result.buttons is not None
    assert result.document is None
    mock_store.assert_called_once()
    stored_data = mock_store.call_args[0][1]
    due_iso = stored_data["due_date_iso"]
    expected_due = date.today() + timedelta(days=15)
    assert due_iso == expected_due.isoformat()


# ---------------------------------------------------------------------------
# Preview has confirm buttons
# ---------------------------------------------------------------------------

async def test_preview_has_confirm_buttons():
    """Invoice shows preview with confirm/edit/cancel buttons."""
    ctx = _make_context()
    msg = _make_message("invoice Mike for consulting $1000")
    intent_data = {"contact_name": "Mike"}
    contact = _mock_contact(name="Mike")
    contact_sess = _mock_async_session(scalar_value=contact)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [
                    {"description": "Consulting", "quantity": 1, "unit_price": 1000.0},
                ],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, intent_data)

    mock_store.assert_called_once()
    assert result.buttons is not None
    assert len(result.buttons) == 3
    callbacks = [b["callback"] for b in result.buttons]
    assert any(cb.startswith("invoice_confirm:") for cb in callbacks)
    assert any(cb.startswith("invoice_edit:") for cb in callbacks)
    assert any(cb.startswith("invoice_cancel:") for cb in callbacks)
    assert "1000.00" in result.response_text or "1,000" in result.response_text
    assert result.document is None


# ---------------------------------------------------------------------------
# Invoice number format
# ---------------------------------------------------------------------------

async def test_invoice_number_format():
    """Invoice number is YYYYMM-XXXX format."""
    num = _generate_invoice_number()
    today = date.today()
    prefix = today.strftime("%Y%m")
    assert num.startswith(prefix + "-")
    assert len(num.split("-")[1]) == 4


# ---------------------------------------------------------------------------
# Company info from profile
# ---------------------------------------------------------------------------

async def test_company_info_from_profile():
    """Company name comes from profile_config if available."""
    ctx = _make_context()
    profile = MagicMock()
    profile.business_name = "Chen Plumbing LLC"
    profile.address = "123 Main St"
    profile.phone = "555-0000"
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="plumber",
        categories=[],
        merchant_mappings=[],
        profile_config=profile,
    )
    msg = _make_message("invoice Mike for work $500")
    intent_data = {"contact_name": "Mike"}
    contact = _mock_contact(name="Mike")
    contact_sess = _mock_async_session(scalar_value=contact)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [
                    {"description": "Work", "quantity": 1, "unit_price": 500.0},
                ],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        await skill.execute(msg, ctx, intent_data)

    stored = mock_store.call_args[0][1]
    assert stored["company_name"] == "Chen Plumbing LLC"
    assert stored["company_address"] == "123 Main St"


# ---------------------------------------------------------------------------
# i18n: Russian and Spanish previews
# ---------------------------------------------------------------------------

async def test_i18n_preview_russian():
    """Preview uses Russian strings."""
    data = {
        "invoice_number": "202603-ABCD",
        "client_name": "Иванов Иван",
        "client_email": "ivan@test.com",
        "currency_symbol": "$",
        "total": 1000.0,
        "due_date": "March 31, 2026",
        "items": [{"description": "Ремонт", "quantity": 1, "unit_price": 1000.0, "amount": 1000.0}],
        "notes": None,
    }
    preview = _format_preview(data, "ru")
    assert "Предпросмотр" in preview
    assert "Иванов" in preview
    assert "1000.00" in preview


async def test_i18n_preview_spanish():
    """Preview uses Spanish strings."""
    data = {
        "invoice_number": "202603-ABCD",
        "client_name": "Carlos",
        "client_email": None,
        "currency_symbol": "$",
        "total": 500.0,
        "due_date": "March 31, 2026",
        "items": [
            {"description": "Plumbing", "quantity": 1, "unit_price": 500.0, "amount": 500.0},
        ],
        "notes": None,
    }
    preview = _format_preview(data, "es")
    assert "Vista previa" in preview
    assert "Carlos" in preview


# ---------------------------------------------------------------------------
# Redis pending helpers (unit tests)
# ---------------------------------------------------------------------------

async def test_store_and_get_pending():
    """Store and retrieve pending invoice via Redis."""
    pid = "test1234"
    data = {"invoice_number": "202603-TEST", "total": 100.0}

    with patch("src.skills.generate_invoice.handler.redis") as mock_redis:
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(data))
        mock_redis.delete = AsyncMock()

        await store_pending_invoice(pid, data)
        mock_redis.set.assert_called_once()
        assert "invoice_pending:test1234" in mock_redis.set.call_args[0][0]

        result = await get_pending_invoice(pid)
        assert result["invoice_number"] == "202603-TEST"

        await delete_pending_invoice(pid)
        mock_redis.delete.assert_called_once()


async def test_get_pending_returns_none_when_expired():
    """Returns None for expired/missing pending invoice."""
    with patch("src.skills.generate_invoice.handler.redis") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        result = await get_pending_invoice("expired123")
    assert result is None


# ---------------------------------------------------------------------------
# Intent data items pass-through
# ---------------------------------------------------------------------------

async def test_intent_data_items_override():
    """Items from intent_data.invoice_items override LLM extraction."""
    ctx = _make_context()
    msg = _make_message("invoice Mike for stuff")
    intent_data = {
        "contact_name": "Mike",
        "invoice_items": [
            {"description": "Custom item", "quantity": 2, "unit_price": 250.0},
        ],
    }
    contact = _mock_contact(name="Mike")
    contact_sess = _mock_async_session(scalar_value=contact)

    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        await skill.execute(msg, ctx, intent_data)

    stored = mock_store.call_args[0][1]
    assert len(stored["items"]) == 1
    assert stored["items"][0]["description"] == "Custom item"
    assert stored["total"] == 500.0


async def test_invalid_item_payload_is_sanitized():
    """Malformed LLM items are ignored instead of crashing the skill."""
    ctx = _make_context()
    msg = _make_message("invoice Mike")
    intent_data = {"contact_name": "Mike"}
    contact = _mock_contact(name="Mike")
    contact_sess = _mock_async_session(scalar_value=contact)
    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [
                    {"description": "", "quantity": "oops", "unit_price": "x"},
                    {"description": "Work", "quantity": "2", "unit_price": "100"},
                ],
                "due_days": "abc",
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.async_session",
            return_value=contact_sess,
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, intent_data)
    assert result.buttons is not None
    stored = mock_store.call_args[0][1]
    assert len(stored["items"]) == 1
    assert stored["items"][0]["amount"] == 200.0


async def test_preview_marks_tax_pending_when_enabled():
    data = {
        "invoice_number": "202603-ABCD",
        "client_name": "Client",
        "client_email": None,
        "currency_symbol": "$",
        "subtotal": 100.0,
        "total": 100.0,
        "due_date": "March 31, 2026",
        "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0, "amount": 100.0}],
        "notes": None,
        "requires_sales_tax": True,
        "tax_amount": 0.0,
        "tax_rate": 0.0,
    }
    preview = _format_preview(data, "en")
    assert "Sales tax: calculated on confirmation" in preview


async def test_pending_invoice_owner_check():
    ctx = _make_context()
    payload = {"user_id": ctx.user_id, "family_id": ctx.family_id}
    assert is_pending_invoice_owner(payload, ctx) is True
    assert is_pending_invoice_owner({"user_id": "x", "family_id": ctx.family_id}, ctx) is False


async def test_fsm_collects_missing_seller_fields():
    ctx = _make_context(with_profile=False)
    msg = _make_message("invoice Mike for work $100")
    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, {"requires_sales_tax": True})

    assert "seller" in result.response_text.lower() or "продав" in result.response_text.lower()
    stored = mock_store.call_args[0][1]
    assert stored["draft_state"] == "collect_seller"
    assert "company_name" in stored["missing_seller_fields"]
    assert "company_address" in stored["missing_seller_fields"]
    assert "seller_state" in stored["missing_seller_fields"]


async def test_fsm_creates_new_buyer_when_contact_missing_and_details_provided():
    ctx = _make_context()
    msg = _make_message("invoice New Buyer for work $100")
    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "New Buyer",
                "items": [{"description": "Work", "quantity": 1, "unit_price": 100.0}],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler._find_contacts",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.generate_invoice.handler._create_contact",
            new_callable=AsyncMock,
            return_value={
                "id": str(uuid.uuid4()),
                "name": "New Buyer",
                "email": "buyer@test.com",
                "phone": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(
            msg,
            ctx,
            {
                "company_name": "Seller Inc",
                "company_address": "1 Main St",
                "contact_email": "buyer@test.com",
            },
        )

    response = result.response_text.lower()
    assert "new buyer" in response or "buyer contact" in response
    stored = mock_store.call_args[0][1]
    assert stored["draft_state"] == "await_confirm"
    assert stored["contact_name"] == "New Buyer"


async def test_fsm_requires_buyer_tax_address_when_sales_tax_enabled():
    ctx = _make_context()
    msg = _make_message("invoice Mike for service $200")
    with (
        patch(
            "src.skills.generate_invoice.handler._parse_invoice_request",
            new_callable=AsyncMock,
            return_value={
                "contact_name": "Mike",
                "items": [{"description": "Service", "quantity": 1, "unit_price": 200.0}],
                "due_days": 30,
                "notes": None,
            },
        ),
        patch(
            "src.skills.generate_invoice.handler._find_contacts",
            new_callable=AsyncMock,
            return_value=[{"id": str(uuid.uuid4()), "name": "Mike", "email": None, "phone": None}],
        ),
        patch(
            "src.skills.generate_invoice.handler.store_pending_invoice",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result = await skill.execute(
            msg,
            ctx,
            {
                "requires_sales_tax": True,
                "seller_state": "NY",
                "company_name": "Seller Inc",
                "company_address": "1 Main St",
            },
        )

    assert "buyer" in result.response_text.lower() or "покупател" in result.response_text.lower()
    stored = mock_store.call_args[0][1]
    assert stored["draft_state"] == "collect_buyer"
    assert "buyer_state" in stored["missing_buyer_fields"]
    assert "buyer_postal_code" in stored["missing_buyer_fields"]


async def test_contact_candidate_resolution_supports_numeric_choice():
    candidates = [
        {"id": "1", "name": "Mike Chen", "email": None, "phone": None},
        {"id": "2", "name": "Michael Scott", "email": None, "phone": None},
    ]
    resolved = _resolve_contact_name_from_candidates("2", candidates)
    assert resolved is not None
    assert resolved["name"] == "Michael Scott"
