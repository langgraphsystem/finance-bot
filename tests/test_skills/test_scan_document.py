"""Tests for ScanDocumentSkill — universal document scanner."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.scan_document.handler import ScanDocumentSkill


@pytest.fixture
def skill():
    return ScanDocumentSkill()


@pytest.fixture
def context():
    return SessionContext(
        user_id="00000000-0000-0000-0000-000000000001",
        family_id="00000000-0000-0000-0000-000000000002",
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucking",
        categories=[
            {
                "id": "00000000-0000-0000-0000-000000000010",
                "name": "Fuel",
                "scope": "business",
                "icon": "⛽",
            }
        ],
        merchant_mappings=[],
    )


@pytest.fixture
def photo_message():
    return IncomingMessage(
        id="1",
        user_id="12345",
        chat_id="12345",
        type=MessageType.photo,
        photo_bytes=b"fake_image_data",
    )


@pytest.fixture
def document_message():
    return IncomingMessage(
        id="2",
        user_id="12345",
        chat_id="12345",
        type=MessageType.document,
        document_bytes=b"fake_pdf_data",
        document_mime_type="application/pdf",
        document_file_name="invoice.pdf",
    )


@pytest.fixture
def mock_redis():
    """Mock Redis for pending doc storage."""
    with patch("src.skills.scan_document.handler.redis") as mock_r:
        mock_r.set = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.delete = AsyncMock()
        yield mock_r


@pytest.mark.asyncio
async def test_no_image_returns_prompt(skill, context):
    """When no photo or document is provided, ask user to send one."""
    msg = IncomingMessage(id="1", user_id="12345", chat_id="12345", type=MessageType.text)
    result = await skill.execute(msg, context, {})
    assert "Отправьте фото" in result.response_text


@pytest.mark.asyncio
async def test_classify_receipt(skill):
    """Test classification returns valid document type."""
    mock_response = MagicMock()
    mock_response.text = "receipt"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill._classify(b"fake_image", "image/jpeg")
    assert result == "receipt"


@pytest.mark.asyncio
async def test_classify_invoice(skill):
    """Test classification detects invoices."""
    mock_response = MagicMock()
    mock_response.text = "invoice"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill._classify(b"fake_image", "image/jpeg")
    assert result == "invoice"


@pytest.mark.asyncio
async def test_classify_rate_confirmation(skill):
    """Test classification detects rate confirmations."""
    mock_response = MagicMock()
    mock_response.text = "rate_confirmation"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill._classify(b"fake_image", "image/jpeg")
    assert result == "rate_confirmation"


@pytest.mark.asyncio
async def test_classify_unknown_defaults_to_other(skill):
    """Unknown classification falls back to 'other'."""
    mock_response = MagicMock()
    mock_response.text = "some random text"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill._classify(b"fake_image", "image/jpeg")
    assert result == "other"


@pytest.mark.asyncio
async def test_execute_receipt(skill, context, photo_message, mock_redis):
    """Full flow: classify as receipt → extract → store in Redis → format."""
    classify_resp = MagicMock()
    classify_resp.text = "receipt"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps(
        {
            "merchant": "Walmart",
            "total": 42.50,
            "date": "2026-02-13",
            "items": [{"name": "Milk", "quantity": 1, "price": 3.50}],
            "tax": 2.50,
        }
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(photo_message, context, {})

    assert "Walmart" in result.response_text
    assert "42.5" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) >= 2
    # Verify pending doc stored in Redis
    mock_redis.set.assert_awaited_once()
    call_args = mock_redis.set.call_args
    key = call_args[0][0]
    assert key.startswith("pending_doc:")
    stored_data = json.loads(call_args[0][1])
    assert stored_data["doc_type"] == "receipt"
    assert stored_data["ocr_data"]["merchant"] == "Walmart"
    assert stored_data["image_b64"]  # image bytes stored
    assert stored_data["user_id"] == context.user_id
    assert stored_data["family_id"] == context.family_id


@pytest.mark.asyncio
async def test_execute_invoice(skill, context, photo_message, mock_redis):
    """Full flow: classify as invoice → extract → store → format."""
    classify_resp = MagicMock()
    classify_resp.text = "invoice"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps(
        {
            "vendor": "AWS",
            "invoice_number": "INV-2026-001",
            "total": 150.00,
            "date": "2026-02-01",
            "due_date": "2026-03-01",
        }
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(photo_message, context, {})

    assert "AWS" in result.response_text
    assert "INV-2026-001" in result.response_text
    assert result.buttons is not None
    # Verify Redis storage
    stored_data = json.loads(mock_redis.set.call_args[0][1])
    assert stored_data["doc_type"] == "invoice"
    assert stored_data["ocr_data"]["vendor"] == "AWS"


@pytest.mark.asyncio
async def test_execute_rate_conf(skill, context, photo_message, mock_redis):
    """Full flow: classify as rate_confirmation → extract → store → format."""
    classify_resp = MagicMock()
    classify_resp.text = "rate_confirmation"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps(
        {
            "broker": "XPO Logistics",
            "origin": "Los Angeles, CA",
            "destination": "Chicago, IL",
            "rate": 2500.00,
            "ref_number": "REF-12345",
        }
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(photo_message, context, {})

    assert "XPO Logistics" in result.response_text
    assert "2500" in result.response_text
    assert "Los Angeles" in result.response_text
    assert result.buttons is not None
    # Verify Redis storage includes all load fields
    stored_data = json.loads(mock_redis.set.call_args[0][1])
    assert stored_data["doc_type"] == "rate_confirmation"
    assert stored_data["ocr_data"]["origin"] == "Los Angeles, CA"
    assert stored_data["ocr_data"]["destination"] == "Chicago, IL"


@pytest.mark.asyncio
async def test_execute_generic_document(skill, context, photo_message, mock_redis):
    """Full flow: classify as other → extract → store → format."""
    classify_resp = MagicMock()
    classify_resp.text = "other"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps(
        {
            "title": "Contract Agreement",
            "doc_type": "contract",
            "summary": "Agreement between parties for services",
            "key_values": {"Party A": "Company X", "Party B": "Company Y"},
            "dates": ["2026-01-01"],
            "amounts": ["$5000"],
            "extracted_text": "Full contract text here...",
        }
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(photo_message, context, {})

    assert "Contract Agreement" in result.response_text
    assert "contract" in result.response_text
    assert "Company X" in result.response_text
    # Generic docs also have save button
    assert result.buttons is not None


@pytest.mark.asyncio
async def test_claude_fallback_on_gemini_failure(skill, context, photo_message, mock_redis):
    """When Gemini extraction fails, Claude fallback is used."""
    classify_resp = MagicMock()
    classify_resp.text = "receipt"

    mock_google = MagicMock()
    mock_google.aio.models.generate_content = AsyncMock(
        side_effect=[classify_resp, RuntimeError("Gemini down")]
    )

    claude_response = MagicMock()
    claude_response.content = [MagicMock(text=json.dumps({"merchant": "Target", "total": 25.00}))]
    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=claude_response)

    with (
        patch("src.skills.scan_document.handler.google_client", return_value=mock_google),
        patch("src.skills.scan_document.handler.anthropic_client", return_value=mock_anthropic),
    ):
        result = await skill.execute(photo_message, context, {})

    assert "Target" in result.response_text
    # Verify fallback_used is recorded
    stored_data = json.loads(mock_redis.set.call_args[0][1])
    assert stored_data["fallback_used"] is True


@pytest.mark.asyncio
async def test_all_ocr_fails(skill, context, photo_message, mock_redis):
    """When both Gemini and Claude fail, return error message."""
    classify_resp = MagicMock()
    classify_resp.text = "receipt"

    mock_google = MagicMock()
    mock_google.aio.models.generate_content = AsyncMock(
        side_effect=[classify_resp, RuntimeError("Gemini down")]
    )

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(side_effect=RuntimeError("Claude down"))

    with (
        patch("src.skills.scan_document.handler.google_client", return_value=mock_google),
        patch("src.skills.scan_document.handler.anthropic_client", return_value=mock_anthropic),
    ):
        result = await skill.execute(photo_message, context, {})

    assert "Не удалось" in result.response_text
    # Redis should NOT be called for failed scan
    mock_redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_message_with_bytes(skill, context, document_message, mock_redis):
    """Document messages (PDF) are handled via document_bytes."""
    classify_resp = MagicMock()
    classify_resp.text = "invoice"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps(
        {
            "vendor": "Google Cloud",
            "total": 300.00,
            "invoice_number": "GCP-001",
        }
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(document_message, context, {})

    assert "Google Cloud" in result.response_text
    assert "300" in result.response_text
    # Verify mime_type from document is stored
    stored_data = json.loads(mock_redis.set.call_args[0][1])
    assert stored_data["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_callback_contains_pending_id(skill, context, photo_message, mock_redis):
    """Callback buttons carry only the pending_id for Redis lookup."""
    classify_resp = MagicMock()
    classify_resp.text = "receipt"

    extract_resp = MagicMock()
    extract_resp.text = json.dumps({"merchant": "Shell", "total": 50.00})

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=[classify_resp, extract_resp])

    with patch("src.skills.scan_document.handler.google_client", return_value=mock_client):
        result = await skill.execute(photo_message, context, {})

    # Callback should be doc_save:<pending_id> — no data in callback
    save_btn = result.buttons[0]
    assert save_btn["callback"].startswith("doc_save:")
    parts = save_btn["callback"].split(":")
    assert len(parts) == 2  # doc_save + pending_id only
    pending_id = parts[1]
    assert len(pending_id) == 8  # uuid[:8]


def test_skill_intents():
    """Skill handles both scan_document and scan_receipt intents."""
    skill = ScanDocumentSkill()
    assert "scan_document" in skill.intents
    assert "scan_receipt" in skill.intents


def test_skill_name():
    skill = ScanDocumentSkill()
    assert skill.name == "scan_document"
