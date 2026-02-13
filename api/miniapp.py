"""Mini App REST API — endpoints for Telegram WebView SPA."""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from api.webapp_auth import validate_webapp_data
from src.core.db import async_session
from src.core.models.category import Category
from src.core.models.enums import Scope, TransactionType
from src.core.models.transaction import Transaction
from src.core.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["miniapp"])


# --- Response schemas ---


class CategoryStats(BaseModel):
    name: str
    icon: str | None = None
    total: float
    percent: float


class StatsResponse(BaseModel):
    period: str
    total_expense: float
    total_income: float
    balance: float
    expense_categories: list[CategoryStats]


class TransactionItem(BaseModel):
    id: str
    type: str
    amount: float
    category: str
    merchant: str | None = None
    description: str | None = None
    date: str


class TransactionListResponse(BaseModel):
    items: list[TransactionItem]
    total: int
    page: int
    per_page: int


class TransactionCreateRequest(BaseModel):
    amount: float = Field(gt=0)
    category_id: str
    type: str = "expense"
    merchant: str | None = None
    description: str | None = None
    date: str | None = None  # ISO format, defaults to today


class SettingsResponse(BaseModel):
    language: str
    currency: str
    business_type: str | None
    categories: list[dict[str, Any]]


class SettingsUpdateRequest(BaseModel):
    language: str | None = None
    currency: str | None = None


# --- Helper to get user from Telegram data ---


async def get_current_user(
    telegram_data: dict = Depends(validate_webapp_data),
) -> User:
    telegram_id = telegram_data.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="No telegram ID")
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == int(telegram_id)))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user


# --- Endpoints ---


@router.get("/stats/{period}", response_model=StatsResponse)
async def get_stats(
    period: str = "month",
    user: User = Depends(get_current_user),
):
    """Get spending statistics for a period."""
    today = date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:
        start = today.replace(day=1)
        period = "month"

    async with async_session() as session:
        # Expenses by category
        exp_result = await session.execute(
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == user.family_id,
                Transaction.date >= start,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name, Category.icon)
            .order_by(desc("total"))
        )
        expense_rows = exp_result.all()

        total_expense = sum(float(r[2]) for r in expense_rows)

        # Total income
        inc_result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == user.family_id,
                Transaction.date >= start,
                Transaction.type == TransactionType.income,
            )
        )
        total_income = float(inc_result.scalar() or 0)

    categories = [
        CategoryStats(
            name=r[0],
            icon=r[1],
            total=float(r[2]),
            percent=(float(r[2]) / total_expense * 100) if total_expense > 0 else 0,
        )
        for r in expense_rows
    ]

    return StatsResponse(
        period=period,
        total_expense=total_expense,
        total_income=total_income,
        balance=total_income - total_expense,
        expense_categories=categories,
    )


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    type: str | None = None,
    user: User = Depends(get_current_user),
):
    """List transactions with pagination."""
    async with async_session() as session:
        query = (
            select(Transaction, Category.name.label("cat_name"))
            .join(Category, Transaction.category_id == Category.id)
            .where(Transaction.family_id == user.family_id)
        )
        if type:
            query = query.where(Transaction.type == TransactionType(type))

        # Count total
        count_q = select(func.count(Transaction.id)).where(Transaction.family_id == user.family_id)
        total = (await session.execute(count_q)).scalar() or 0

        # Fetch page
        query = query.order_by(desc(Transaction.date)).offset((page - 1) * per_page).limit(per_page)
        result = await session.execute(query)
        rows = result.all()

    items = [
        TransactionItem(
            id=str(tx.id),
            type=tx.type.value,
            amount=float(tx.amount),
            category=cat_name,
            merchant=tx.merchant,
            description=tx.description,
            date=tx.date.isoformat(),
        )
        for tx, cat_name in rows
    ]

    return TransactionListResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("/transactions", response_model=TransactionItem)
async def create_transaction(
    data: TransactionCreateRequest,
    user: User = Depends(get_current_user),
):
    """Create a transaction from Mini App form."""
    tx_date = date.fromisoformat(data.date) if data.date else date.today()
    tx_type = TransactionType(data.type)

    async with async_session() as session:
        tx = Transaction(
            family_id=user.family_id,
            user_id=user.id,
            category_id=uuid.UUID(data.category_id),
            type=tx_type,
            amount=Decimal(str(data.amount)),
            merchant=data.merchant,
            description=data.description,
            date=tx_date,
            scope=Scope.family,
            ai_confidence=Decimal("1.0"),
            meta={"source": "miniapp"},
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        # Get category name
        cat = await session.execute(select(Category.name).where(Category.id == tx.category_id))
        cat_name = cat.scalar() or ""

    return TransactionItem(
        id=str(tx.id),
        type=tx.type.value,
        amount=float(tx.amount),
        category=cat_name,
        merchant=tx.merchant,
        description=tx.description,
        date=tx.date.isoformat(),
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
):
    """Update user settings."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()

        if data.language:
            db_user.language = data.language
        if data.currency:
            from src.core.models.family import Family

            fam = await session.execute(select(Family).where(Family.id == db_user.family_id))
            family = fam.scalar_one()
            family.currency = data.currency

        await session.commit()

        # Return updated settings
        cats = await session.execute(
            select(Category).where(Category.family_id == db_user.family_id)
        )
        categories = [
            {"id": str(c.id), "name": c.name, "icon": c.icon, "scope": c.scope.value}
            for c in cats.scalars()
        ]

    return SettingsResponse(
        language=db_user.language,
        currency=data.currency or "USD",
        business_type=db_user.business_type,
        categories=categories,
    )
