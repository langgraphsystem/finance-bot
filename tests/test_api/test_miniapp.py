"""Tests for Mini App REST API endpoints."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.miniapp import (
    CategoryStats,
    SettingsResponse,
    StatsResponse,
    TransactionCreateRequest,
    TransactionItem,
    TransactionListResponse,
    get_current_user,
    router,
)

BOT_TOKEN = "test_token"


def _build_valid_init_data(telegram_id: int = 123456) -> str:
    """Build a properly signed init data string for testing."""
    user = {"id": telegram_id, "first_name": "Test", "username": "testuser"}
    auth_date = int(time.time())
    params = {
        "auth_date": str(auth_date),
        "user": json.dumps(user),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    params["hash"] = calculated_hash
    return urlencode(params)


# --- Pydantic schema tests ---


def test_stats_response_schema():
    """StatsResponse model creates correctly."""
    resp = StatsResponse(
        period="month",
        total_expense=1500.0,
        total_income=3000.0,
        balance=1500.0,
        currency="USD",
        expense_categories=[
            CategoryStats(name="Food", icon="🍔", total=800.0, percent=53.3),
            CategoryStats(name="Gas", icon="⛽", total=700.0, percent=46.7),
        ],
        income_categories=[],
    )
    assert resp.period == "month"
    assert resp.balance == 1500.0
    assert len(resp.expense_categories) == 2


def test_transaction_item_schema():
    """TransactionItem model creates correctly."""
    item = TransactionItem(
        id=str(uuid.uuid4()),
        type="expense",
        amount=42.50,
        category="Fuel",
        category_id=str(uuid.uuid4()),
        merchant="Shell",
        description="Diesel",
        date="2026-02-10",
        scope="family",
    )
    assert item.type == "expense"
    assert item.amount == 42.50
    assert item.merchant == "Shell"


def test_transaction_list_response_schema():
    """TransactionListResponse with pagination."""
    resp = TransactionListResponse(items=[], total=0, page=1, per_page=20)
    assert resp.total == 0
    assert resp.page == 1


def test_transaction_create_request_validation():
    """TransactionCreateRequest validates amount > 0."""
    req = TransactionCreateRequest(
        amount=50.0,
        category_id=str(uuid.uuid4()),
        type="expense",
    )
    assert req.amount == 50.0
    assert req.type == "expense"


def test_transaction_create_request_rejects_negative():
    """TransactionCreateRequest rejects negative amount."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransactionCreateRequest(
            amount=-10.0,
            category_id=str(uuid.uuid4()),
        )


def test_transaction_create_request_rejects_zero():
    """TransactionCreateRequest rejects zero amount."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TransactionCreateRequest(
            amount=0,
            category_id=str(uuid.uuid4()),
        )


def test_settings_response_schema():
    """SettingsResponse model creates correctly."""
    resp = SettingsResponse(
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[{"id": str(uuid.uuid4()), "name": "Fuel", "icon": "⛽", "scope": "business"}],
    )
    assert resp.language == "ru"
    assert len(resp.categories) == 1


# --- Integration tests using TestClient with mocked dependencies ---


def _create_test_app(auth_user_override=None):
    """Create a test FastAPI app with the miniapp router and mocked auth."""
    test_app = FastAPI()

    if auth_user_override is not None:
        # Override the get_current_user dependency to return a mock user
        async def _override_get_current_user():
            return auth_user_override

        test_app.include_router(router)
        test_app.dependency_overrides[get_current_user] = _override_get_current_user
    else:
        test_app.include_router(router)

    return test_app


def _make_mock_user():
    """Create a mock User object for tests."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.family_id = uuid.uuid4()
    user.telegram_id = 123456
    user.language = "ru"
    user.business_type = "trucker"
    user.role = MagicMock()
    user.role.value = "owner"
    return user


class TestGetStatsEndpoint:
    """Tests for GET /api/stats/{period}."""

    def test_stats_month_returns_correct_structure(self):
        """GET /api/stats/month returns StatsResponse structure."""
        mock_user = _make_mock_user()
        cat_id = uuid.uuid4()

        # Stats endpoint: scalar(Family), execute(expense cats), execute(income cats)
        mock_exp_rows = [
            (cat_id, "Food", "🍔", Decimal("800.00")),
            (cat_id, "Gas", "⛽", Decimal("200.00")),
        ]
        mock_inc_rows: list = []

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_fam = MagicMock()
            mock_fam.currency = "USD"
            mock_session.scalar = AsyncMock(return_value=mock_fam)

            exp_result = MagicMock()
            exp_result.all.return_value = mock_exp_rows
            inc_result = MagicMock()
            inc_result.all.return_value = mock_inc_rows

            mock_session.execute = AsyncMock(side_effect=[exp_result, inc_result])

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.get("/api/stats/month")

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "month"
        assert data["total_expense"] == 1000.0
        assert data["total_income"] == 0.0
        assert data["balance"] == -1000.0
        assert data["currency"] == "USD"
        assert len(data["expense_categories"]) == 2
        assert data["expense_categories"][0]["name"] == "Food"
        assert data["expense_categories"][0]["percent"] == 80.0

    def test_stats_week_period(self):
        """GET /api/stats/week uses correct period."""
        mock_user = _make_mock_user()

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_fam = MagicMock()
            mock_fam.currency = "USD"
            mock_session.scalar = AsyncMock(return_value=mock_fam)

            exp_result = MagicMock()
            exp_result.all.return_value = []
            inc_result = MagicMock()
            inc_result.all.return_value = []

            mock_session.execute = AsyncMock(side_effect=[exp_result, inc_result])

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.get("/api/stats/week")

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "week"
        assert data["total_expense"] == 0
        assert data["total_income"] == 0


class TestListTransactionsEndpoint:
    """Tests for GET /api/transactions."""

    def test_transactions_returns_paginated_list(self):
        """GET /api/transactions returns TransactionListResponse."""
        mock_user = _make_mock_user()
        tx_id = uuid.uuid4()
        cat_id = uuid.uuid4()

        mock_tx = MagicMock()
        mock_tx.id = tx_id
        mock_tx.type = MagicMock()
        mock_tx.type.value = "expense"
        mock_tx.amount = Decimal("42.50")
        mock_tx.merchant = "Shell"
        mock_tx.description = "Diesel"
        mock_tx.date = date(2026, 2, 10)
        mock_tx.scope = MagicMock()
        mock_tx.scope.value = "family"

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            # Count via session.scalar(); rows via session.execute()
            mock_session.scalar = AsyncMock(return_value=1)
            data_result = MagicMock()
            data_result.all.return_value = [(mock_tx, "Fuel", cat_id)]
            mock_session.execute = AsyncMock(return_value=data_result)

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.get("/api/transactions?page=1&per_page=20")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == str(tx_id)
        assert data["items"][0]["category"] == "Fuel"
        assert data["items"][0]["amount"] == 42.50

    def test_transactions_empty_list(self):
        """GET /api/transactions returns empty when no data."""
        mock_user = _make_mock_user()

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_session.scalar = AsyncMock(return_value=0)
            data_result = MagicMock()
            data_result.all.return_value = []
            mock_session.execute = AsyncMock(return_value=data_result)

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.get("/api/transactions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestCreateTransactionEndpoint:
    """Tests for POST /api/transactions."""

    def test_create_transaction_success(self):
        """POST /api/transactions creates and returns transaction."""
        mock_user = _make_mock_user()
        cat_id = uuid.uuid4()
        tx_id = uuid.uuid4()

        mock_cat = MagicMock()
        mock_cat.id = cat_id
        mock_cat.name = "Groceries"

        mock_tx = MagicMock()
        mock_tx.id = tx_id
        mock_tx.type = MagicMock()
        mock_tx.type.value = "expense"
        mock_tx.amount = Decimal("50.00")
        mock_tx.merchant = "Walmart"
        mock_tx.description = "Groceries"
        mock_tx.date = date(2026, 2, 13)
        mock_tx.category_id = cat_id
        mock_tx.scope = MagicMock()
        mock_tx.scope.value = "family"

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()

            # session.scalar() returns category; refresh populates tx
            mock_session.scalar = AsyncMock(return_value=mock_cat)

            async def _fake_refresh(obj):
                obj.id = mock_tx.id
                obj.type = mock_tx.type
                obj.amount = mock_tx.amount
                obj.merchant = mock_tx.merchant
                obj.description = mock_tx.description
                obj.date = mock_tx.date
                obj.category_id = mock_tx.category_id
                obj.scope = mock_tx.scope

            mock_session.refresh = _fake_refresh

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.post(
                "/api/transactions",
                json={
                    "amount": 50.0,
                    "category_id": str(cat_id),
                    "type": "expense",
                    "merchant": "Walmart",
                    "description": "Groceries",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["amount"] == 50.0
        assert data["category"] == "Groceries"
        assert data["type"] == "expense"


class TestUpdateSettingsEndpoint:
    """Tests for PUT /api/settings."""

    def test_update_settings_language(self):
        """PUT /api/settings updates language and returns settings."""
        mock_user = _make_mock_user()

        mock_db_user = MagicMock()
        mock_db_user.id = mock_user.id
        mock_db_user.family_id = mock_user.family_id
        mock_db_user.language = "en"
        mock_db_user.business_type = "trucker"

        mock_fam = MagicMock()
        mock_fam.currency = "USD"

        cat_id = uuid.uuid4()
        mock_cat = MagicMock()
        mock_cat.id = cat_id
        mock_cat.name = "Fuel"
        mock_cat.icon = "⛽"
        mock_cat.scope = MagicMock()
        mock_cat.scope.value = "business"

        with patch("api.miniapp.async_session") as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            # Two scalar() calls: user then family
            mock_session.scalar = AsyncMock(side_effect=[mock_db_user, mock_fam])
            mock_session.commit = AsyncMock()

            # One execute() call for categories
            cats_result = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [mock_cat]
            cats_result.scalars.return_value = scalars_mock
            mock_session.execute = AsyncMock(return_value=cats_result)

            app = _create_test_app(auth_user_override=mock_user)
            client = TestClient(app)
            response = client.put(
                "/api/settings",
                json={"language": "en"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["language"] == "en"
        assert data["business_type"] == "trucker"
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "Fuel"
