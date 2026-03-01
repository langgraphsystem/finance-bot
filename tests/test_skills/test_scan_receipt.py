"""Tests for ScanReceiptSkill."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.core.schemas.receipt import ReceiptData
from src.skills.scan_receipt.handler import ScanReceiptSkill, skill


@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis for pending receipt storage in all tests."""
    with patch("src.skills.scan_receipt.handler.redis") as mock_r:
        mock_r.set = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.delete = AsyncMock()
        yield mock_r


def _make_receipt(**overrides) -> ReceiptData:
    """Create a ReceiptData with sensible defaults."""
    data = {
        "merchant": "Shell Gas Station",
        "total": 45.67,
        "date": "2026-02-20",
        "items": [{"name": "Diesel", "price": 45.67}],
        "tax": 3.50,
        "state": None,
        "gallons": None,
        "price_per_gallon": None,
    }
    data.update(overrides)
    return ReceiptData(**data)


async def test_no_photo_returns_error(sample_context, text_message):
    """Text message without photo returns error asking for photo."""
    result = await skill.execute(text_message, sample_context, {})
    assert "Отправьте фото чека" in result.response_text


async def test_gemini_ocr_success(sample_context, photo_message):
    """Gemini OCR succeeds — business user sees scope selection buttons."""
    receipt = _make_receipt(merchant="Walmart", total=123.45)

    with patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt):
        result = await skill.execute(photo_message, sample_context, {})

    assert "Walmart" in result.response_text
    assert "123.45" in result.response_text
    assert result.buttons is not None
    # Business user gets scope selection buttons (not receipt_confirm)
    callback_values = [
        b.get("callback", "") if isinstance(b, dict) else str(b)
        for b in result.buttons
    ]
    assert any("receipt_scope" in v for v in callback_values)
    assert any("business" in v for v in callback_values)
    assert any("family" in v for v in callback_values)


async def test_gemini_fallback_to_claude(sample_context, photo_message):
    """When Gemini OCR raises, falls back to Claude OCR."""
    receipt = _make_receipt(merchant="Target", total=55.00)

    with (
        patch.object(
            skill, "_ocr_gemini", new_callable=AsyncMock, side_effect=Exception("Gemini down")
        ),
        patch.object(skill, "_ocr_claude", new_callable=AsyncMock, return_value=receipt),
    ):
        result = await skill.execute(photo_message, sample_context, {})

    assert "Target" in result.response_text
    assert "55" in result.response_text


async def test_all_ocr_fails(sample_context, photo_message):
    """Both OCR engines fail — returns error about unclear photo."""
    with (
        patch.object(
            skill, "_ocr_gemini", new_callable=AsyncMock, side_effect=Exception("Gemini fail")
        ),
        patch.object(
            skill, "_ocr_claude", new_callable=AsyncMock, side_effect=Exception("Claude fail")
        ),
    ):
        result = await skill.execute(photo_message, sample_context, {})

    response_lower = result.response_text.lower()
    assert any(
        phrase in response_lower
        for phrase in ["не удалось", "не смог", "нечёткое", "нечеткое", "попробуйте", "unclear"]
    )


async def test_fuel_receipt_detection(sample_context, photo_message):
    """Receipt with gallons and price_per_gallon is detected as fuel receipt."""
    receipt = _make_receipt(
        merchant="Shell",
        total=89.50,
        gallons=25.0,
        price_per_gallon=3.58,
    )

    with patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt):
        result = await skill.execute(photo_message, sample_context, {})

    response_lower = result.response_text.lower()
    assert any(
        phrase in response_lower
        for phrase in ["заправ", "fuel", "галлон", "gallon", "дизель", "diesel", "топлив", "gal"]
    )


def test_confidence_all_fields():
    """Receipt with all fields → confidence 1.0 (> 0.95 threshold)."""
    receipt = _make_receipt(
        merchant="Walmart", total=50.0, date="2026-02-28",
        items=[{"name": "Milk", "price": 3.50}],
    )
    confidence = ScanReceiptSkill._compute_confidence(receipt)
    assert confidence == Decimal("1.00")


def test_confidence_missing_items():
    """Receipt without items → confidence 0.80."""
    receipt = _make_receipt(merchant="Walmart", total=50.0, date="2026-02-28", items=[])
    confidence = ScanReceiptSkill._compute_confidence(receipt)
    assert confidence == Decimal("0.80")


def test_confidence_missing_date_and_items():
    """Receipt without date or items → confidence 0.60."""
    receipt = _make_receipt(merchant="Walmart", total=50.0, date=None, items=[])
    confidence = ScanReceiptSkill._compute_confidence(receipt)
    assert confidence == Decimal("0.60")


def test_confidence_merchant_only():
    """Only merchant → confidence 0.30."""
    receipt = _make_receipt(merchant="Shell", total=0, date=None, items=[])
    confidence = ScanReceiptSkill._compute_confidence(receipt)
    assert confidence == Decimal("0.30")


async def test_business_user_always_gets_scope_buttons(sample_context, photo_message):
    """Business user always sees scope buttons, even for high-confidence receipts."""
    receipt = _make_receipt(
        merchant="Walmart", total=42.50, date="2026-02-28",
        items=[{"name": "Milk", "price": 3.50}],
    )
    with patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt):
        result = await skill.execute(photo_message, sample_context, {})

    # Business user never auto-saves — always shows scope selection
    assert result.buttons is not None
    callbacks = [b["callback"] for b in result.buttons]
    assert any("receipt_scope" in c and "business" in c for c in callbacks)
    assert any("receipt_scope" in c and "family" in c for c in callbacks)


async def test_auto_save_high_confidence_non_business(photo_message):
    """Non-business user auto-saves high-confidence receipts without buttons."""
    import uuid

    from src.core.context import SessionContext

    non_biz_ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[
            {"id": str(uuid.uuid4()), "name": "Продукты", "scope": "family", "icon": "🛒"},
        ],
        merchant_mappings=[],
    )
    receipt = _make_receipt(
        merchant="Walmart", total=42.50, date="2026-02-28",
        items=[{"name": "Milk", "price": 3.50}],
    )
    with (
        patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt),
        patch.object(
            skill, "_save_receipt_to_db", new_callable=AsyncMock, return_value="tx-123"
        ),
    ):
        result = await skill.execute(photo_message, non_biz_ctx, {})

    assert "Автоматически сохранено" in result.response_text
    assert result.buttons is None


async def test_pending_stored_in_redis(sample_context, photo_message, mock_redis):
    """Business user receipt stores pending data in Redis for scope selection."""
    receipt = _make_receipt(merchant="Shop", total=10.0, date=None, items=[])

    with patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt):
        result = await skill.execute(photo_message, sample_context, {})

    # Should call Redis set (business user always stores pending)
    mock_redis.set.assert_awaited_once()
    key = mock_redis.set.call_args[0][0]
    assert key.startswith("pending_receipt:")
    # Should have scope selection buttons
    assert result.buttons is not None
    callbacks = [b["callback"] for b in result.buttons]
    assert any("receipt_scope" in c for c in callbacks)
