"""Tests for ScanReceiptSkill."""

from unittest.mock import AsyncMock, patch

from src.core.schemas.receipt import ReceiptData
from src.skills.scan_receipt.handler import skill


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
    """Gemini OCR succeeds — response contains merchant and total."""
    receipt = _make_receipt(merchant="Walmart", total=123.45)

    with patch.object(skill, "_ocr_gemini", new_callable=AsyncMock, return_value=receipt):
        result = await skill.execute(photo_message, sample_context, {})

    assert "Walmart" in result.response_text
    assert "123.45" in result.response_text
    assert result.buttons is not None
    # Flatten buttons (may be nested rows)
    flat = []
    for item in result.buttons:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    callback_values = [
        b.get("callback", b.get("callback_data", "")) if isinstance(b, dict) else str(b)
        for b in flat
    ]
    assert any("receipt_confirm" in str(v) for v in callback_values)


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
