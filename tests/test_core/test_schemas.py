"""Tests for Pydantic schemas."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.core.schemas.intent import IntentDetectionResult
from src.core.schemas.receipt import ReceiptData
from src.core.schemas.transaction import TransactionCreate


def test_intent_result_creation():
    result = IntentDetectionResult(
        intent="add_expense",
        confidence=0.95,
        response="Записал расход",
    )
    assert result.intent == "add_expense"
    assert result.confidence == 0.95


def test_receipt_data_creation():
    receipt = ReceiptData(
        merchant="Shell",
        total=Decimal("42.30"),
        date="2026-02-10",
        gallons=12.5,
        price_per_gallon=Decimal("3.384"),
        state="TX",
    )
    assert receipt.merchant == "Shell"
    assert receipt.total == Decimal("42.30")
    assert receipt.gallons == 12.5


def test_transaction_create_validation():
    import uuid
    from datetime import date

    tx = TransactionCreate(
        category_id=uuid.uuid4(),
        type="expense",
        amount=Decimal("50.00"),
        date=date.today(),
        scope="business",
    )
    assert tx.amount == Decimal("50.00")


def test_transaction_amount_must_be_positive():
    import uuid
    from datetime import date

    with pytest.raises(ValidationError):
        TransactionCreate(
            category_id=uuid.uuid4(),
            type="expense",
            amount=Decimal("-10.00"),
            date=date.today(),
            scope="business",
        )
