"""Mini App REST API — endpoints for Telegram WebView SPA."""

import csv
import io
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, select

from api.webapp_auth import validate_webapp_data
from src.core.db import async_session
from src.core.models.budget import Budget
from src.core.models.category import Category
from src.core.models.enums import (
    BudgetPeriod,
    LifeEventType,
    PaymentFrequency,
    Scope,
    TaskPriority,
    TaskStatus,
    TransactionType,
)
from src.core.models.family import Family
from src.core.models.life_event import LifeEvent
from src.core.models.recurring_payment import RecurringPayment
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["miniapp"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CategoryItem(BaseModel):
    id: str
    name: str
    icon: str | None = None
    scope: str


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
    currency: str
    expense_categories: list[CategoryStats]
    income_categories: list[CategoryStats]


class TransactionItem(BaseModel):
    id: str
    type: str
    amount: float
    category: str
    category_id: str
    merchant: str | None = None
    description: str | None = None
    date: str
    scope: str


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
    date: str | None = None


class TransactionUpdateRequest(BaseModel):
    amount: float | None = Field(None, gt=0)
    category_id: str | None = None
    merchant: str | None = None
    description: str | None = None
    date: str | None = None


class SettingsResponse(BaseModel):
    language: str
    currency: str
    business_type: str | None
    categories: list[dict[str, Any]]


class SettingsUpdateRequest(BaseModel):
    language: str | None = None
    currency: str | None = None


class UserProfile(BaseModel):
    id: str
    name: str
    role: str
    language: str
    currency: str
    business_type: str | None
    family_id: str
    family_name: str
    invite_code: str


class BudgetItem(BaseModel):
    id: str
    category_id: str | None
    category_name: str | None
    category_icon: str | None
    scope: str
    amount: float
    period: str
    alert_at: float
    is_active: bool
    spent: float
    percent: float


class BudgetCreateRequest(BaseModel):
    category_id: str | None = None
    scope: str = "family"
    amount: float = Field(gt=0)
    period: str = "monthly"
    alert_at: float = 0.8


class RecurringItem(BaseModel):
    id: str
    name: str
    amount: float
    frequency: str
    next_date: str
    category: str
    category_icon: str | None
    is_active: bool
    auto_record: bool


class RecurringCreateRequest(BaseModel):
    name: str
    amount: float = Field(gt=0)
    category_id: str
    frequency: str = "monthly"
    next_date: str
    auto_record: bool = False


class LifeEventItem(BaseModel):
    id: str
    type: str
    date: str
    text: str | None
    tags: list[str] | None
    data: dict | None
    created_at: str


class LifeEventCreateRequest(BaseModel):
    type: str
    text: str | None = None
    tags: list[str] | None = None
    data: dict | None = None
    date: str | None = None


class TaskItem(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    priority: str
    due_at: str | None
    completed_at: str | None


class TaskCreateRequest(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    due_at: str | None = None


class TaskUpdateRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    title: str | None = None
    description: str | None = None
    due_at: str | None = None


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# User & Family
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile with family info."""
    async with async_session() as session:
        fam = await session.scalar(select(Family).where(Family.id == user.family_id))
        if not fam:
            raise HTTPException(status_code=404, detail="Family not found")
    return UserProfile(
        id=str(user.id),
        name=user.name,
        role=user.role.value,
        language=user.language,
        currency=fam.currency,
        business_type=user.business_type,
        family_id=str(user.family_id),
        family_name=fam.name,
        invite_code=fam.invite_code,
    )


@router.get("/family/invite-code")
async def get_invite_code(user: User = Depends(get_current_user)):
    """Get family invite code (owner only)."""
    async with async_session() as session:
        fam = await session.scalar(select(Family).where(Family.id == user.family_id))
        if not fam:
            raise HTTPException(status_code=404, detail="Family not found")
    return {"invite_code": fam.invite_code, "family_name": fam.name}


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryItem])
async def list_categories(user: User = Depends(get_current_user)):
    """List all categories for the user's family."""
    async with async_session() as session:
        result = await session.execute(
            select(Category)
            .where(Category.family_id == user.family_id)
            .order_by(Category.scope, Category.name)
        )
        cats = result.scalars().all()
    return [CategoryItem(id=str(c.id), name=c.name, icon=c.icon, scope=c.scope.value) for c in cats]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@router.get("/stats/{period}", response_model=StatsResponse)
async def get_stats(
    period: str = "month",
    user: User = Depends(get_current_user),
):
    """Get spending/income statistics for a period."""
    today = date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
    elif period == "year":
        start = today.replace(month=1, day=1)
    else:
        start = today.replace(day=1)
        period = "month"

    async with async_session() as session:
        fam = await session.scalar(select(Family).where(Family.id == user.family_id))
        currency = fam.currency if fam else "USD"

        # Expenses by category
        exp_result = await session.execute(
            select(
                Category.id,
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
            .group_by(Category.id, Category.name, Category.icon)
            .order_by(desc("total"))
        )
        expense_rows = exp_result.all()
        total_expense = sum(float(r[3]) for r in expense_rows)

        # Income by category
        inc_result = await session.execute(
            select(
                Category.id,
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == user.family_id,
                Transaction.date >= start,
                Transaction.type == TransactionType.income,
            )
            .group_by(Category.id, Category.name, Category.icon)
            .order_by(desc("total"))
        )
        income_rows = inc_result.all()
        total_income = sum(float(r[3]) for r in income_rows)

    return StatsResponse(
        period=period,
        total_expense=total_expense,
        total_income=total_income,
        balance=total_income - total_expense,
        currency=currency,
        expense_categories=[
            CategoryStats(
                name=r[1],
                icon=r[2],
                total=float(r[3]),
                percent=(float(r[3]) / total_expense * 100) if total_expense > 0 else 0,
            )
            for r in expense_rows
        ],
        income_categories=[
            CategoryStats(
                name=r[1],
                icon=r[2],
                total=float(r[3]),
                percent=(float(r[3]) / total_income * 100) if total_income > 0 else 0,
            )
            for r in income_rows
        ],
    )


@router.get("/stats/trend/monthly")
async def get_monthly_trend(
    months: int = Query(6, ge=1, le=24),
    user: User = Depends(get_current_user),
):
    """Get month-by-month expense/income trend."""
    today = date.today()
    result = []
    async with async_session() as session:
        for i in range(months - 1, -1, -1):
            month_date = today.replace(day=1) - timedelta(days=i * 28)
            month_date = month_date.replace(day=1)
            if month_date.month == 12:
                end = month_date.replace(year=month_date.year + 1, month=1, day=1)
            else:
                end = month_date.replace(month=month_date.month + 1, day=1)

            exp = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == user.family_id,
                    Transaction.date >= month_date,
                    Transaction.date < end,
                    Transaction.type == TransactionType.expense,
                )
            )
            inc = await session.scalar(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == user.family_id,
                    Transaction.date >= month_date,
                    Transaction.date < end,
                    Transaction.type == TransactionType.income,
                )
            )
            result.append(
                {
                    "month": month_date.strftime("%b %Y"),
                    "expense": float(exp or 0),
                    "income": float(inc or 0),
                }
            )
    return result


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def _tx_to_item(tx: Transaction, cat_name: str, cat_id: str) -> TransactionItem:
    return TransactionItem(
        id=str(tx.id),
        type=tx.type.value,
        amount=float(tx.amount),
        category=cat_name,
        category_id=cat_id,
        merchant=tx.merchant,
        description=tx.description,
        date=tx.date.isoformat(),
        scope=tx.scope.value,
    )


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    type: str | None = None,
    category_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    user: User = Depends(get_current_user),
):
    """List transactions with pagination and filters."""
    async with async_session() as session:
        base_filter = [Transaction.family_id == user.family_id]
        if type:
            base_filter.append(Transaction.type == TransactionType(type))
        if category_id:
            base_filter.append(Transaction.category_id == uuid.UUID(category_id))
        if date_from:
            base_filter.append(Transaction.date >= date.fromisoformat(date_from))
        if date_to:
            base_filter.append(Transaction.date <= date.fromisoformat(date_to))
        if search:
            base_filter.append(
                Transaction.merchant.ilike(f"%{search}%")
                | Transaction.description.ilike(f"%{search}%")
            )

        total = (await session.scalar(select(func.count(Transaction.id)).where(*base_filter))) or 0

        query = (
            select(Transaction, Category.name.label("cat_name"), Category.id.label("cat_id"))
            .join(Category, Transaction.category_id == Category.id)
            .where(*base_filter)
            .order_by(desc(Transaction.date), desc(Transaction.created_at))
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = (await session.execute(query)).all()

    return TransactionListResponse(
        items=[_tx_to_item(tx, cat_name, str(cat_id)) for tx, cat_name, cat_id in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/transactions/{tx_id}", response_model=TransactionItem)
async def get_transaction(
    tx_id: str,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        row = (
            await session.execute(
                select(Transaction, Category.name, Category.id)
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.id == uuid.UUID(tx_id),
                    Transaction.family_id == user.family_id,
                )
            )
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Transaction not found")
        tx, cat_name, cat_id = row
    return _tx_to_item(tx, cat_name, str(cat_id))


@router.post("/transactions", response_model=TransactionItem)
async def create_transaction(
    data: TransactionCreateRequest,
    user: User = Depends(get_current_user),
):
    tx_date = date.fromisoformat(data.date) if data.date else date.today()
    tx_type = TransactionType(data.type)

    async with async_session() as session:
        cat = await session.scalar(
            select(Category).where(
                Category.id == uuid.UUID(data.category_id),
                Category.family_id == user.family_id,
            )
        )
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

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

    return _tx_to_item(tx, cat.name, str(cat.id))


@router.put("/transactions/{tx_id}", response_model=TransactionItem)
async def update_transaction(
    tx_id: str,
    data: TransactionUpdateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        tx = await session.scalar(
            select(Transaction).where(
                Transaction.id == uuid.UUID(tx_id),
                Transaction.family_id == user.family_id,
            )
        )
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if data.amount is not None:
            tx.amount = Decimal(str(data.amount))
        if data.category_id is not None:
            cat_check = await session.scalar(
                select(Category).where(
                    Category.id == uuid.UUID(data.category_id),
                    Category.family_id == user.family_id,
                )
            )
            if not cat_check:
                raise HTTPException(status_code=404, detail="Category not found")
            tx.category_id = uuid.UUID(data.category_id)
        if data.merchant is not None:
            tx.merchant = data.merchant
        if data.description is not None:
            tx.description = data.description
        if data.date is not None:
            tx.date = date.fromisoformat(data.date)
        tx.is_corrected = True

        await session.commit()

        row = (
            await session.execute(
                select(Transaction, Category.name, Category.id)
                .join(Category, Transaction.category_id == Category.id)
                .where(Transaction.id == tx.id)
            )
        ).first()
        tx, cat_name, cat_id = row
    return _tx_to_item(tx, cat_name, str(cat_id))


@router.delete("/transactions/{tx_id}")
async def delete_transaction(
    tx_id: str,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        tx = await session.scalar(
            select(Transaction).where(
                Transaction.id == uuid.UUID(tx_id),
                Transaction.family_id == user.family_id,
            )
        )
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
        await session.delete(tx)
        await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@router.get("/budgets", response_model=list[BudgetItem])
async def list_budgets(user: User = Depends(get_current_user)):
    """List all budgets with current period spending."""
    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    async with async_session() as session:
        budgets = (
            (
                await session.execute(
                    select(Budget)
                    .where(Budget.family_id == user.family_id, Budget.is_active == True)  # noqa: E712
                    .order_by(Budget.period, Budget.created_at)
                )
            )
            .scalars()
            .all()
        )

        result = []
        for b in budgets:
            start = week_start if b.period == BudgetPeriod.weekly else month_start

            spent_filter = [
                Transaction.family_id == user.family_id,
                Transaction.date >= start,
                Transaction.type == TransactionType.expense,
            ]
            if b.category_id:
                spent_filter.append(Transaction.category_id == b.category_id)

            spent = float(
                await session.scalar(select(func.sum(Transaction.amount)).where(*spent_filter)) or 0
            )

            cat_name = None
            cat_icon = None
            if b.category_id:
                cat = await session.scalar(select(Category).where(Category.id == b.category_id))
                if cat:
                    cat_name = cat.name
                    cat_icon = cat.icon

            budget_amount = float(b.amount)
            result.append(
                BudgetItem(
                    id=str(b.id),
                    category_id=str(b.category_id) if b.category_id else None,
                    category_name=cat_name,
                    category_icon=cat_icon,
                    scope=b.scope.value,
                    amount=budget_amount,
                    period=b.period.value,
                    alert_at=float(b.alert_at),
                    is_active=b.is_active,
                    spent=spent,
                    percent=(spent / budget_amount * 100) if budget_amount > 0 else 0,
                )
            )
    return result


@router.post("/budgets", response_model=BudgetItem)
async def create_budget(
    data: BudgetCreateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        b = Budget(
            family_id=user.family_id,
            category_id=uuid.UUID(data.category_id) if data.category_id else None,
            scope=Scope(data.scope),
            amount=Decimal(str(data.amount)),
            period=BudgetPeriod(data.period),
            alert_at=Decimal(str(data.alert_at)),
            is_active=True,
        )
        session.add(b)
        await session.commit()
        await session.refresh(b)

    return BudgetItem(
        id=str(b.id),
        category_id=data.category_id,
        category_name=None,
        category_icon=None,
        scope=b.scope.value,
        amount=float(b.amount),
        period=b.period.value,
        alert_at=float(b.alert_at),
        is_active=b.is_active,
        spent=0,
        percent=0,
    )


@router.delete("/budgets/{budget_id}")
async def delete_budget(budget_id: str, user: User = Depends(get_current_user)):
    async with async_session() as session:
        b = await session.scalar(
            select(Budget).where(
                Budget.id == uuid.UUID(budget_id),
                Budget.family_id == user.family_id,
            )
        )
        if not b:
            raise HTTPException(status_code=404, detail="Budget not found")
        await session.delete(b)
        await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Recurring Payments
# ---------------------------------------------------------------------------


@router.get("/recurring", response_model=list[RecurringItem])
async def list_recurring(user: User = Depends(get_current_user)):
    async with async_session() as session:
        rows = (
            await session.execute(
                select(RecurringPayment, Category.name, Category.icon)
                .join(Category, RecurringPayment.category_id == Category.id)
                .where(
                    RecurringPayment.family_id == user.family_id,
                    RecurringPayment.is_active == True,  # noqa: E712
                )
                .order_by(asc(RecurringPayment.next_date))
            )
        ).all()

    return [
        RecurringItem(
            id=str(r.id),
            name=r.name,
            amount=float(r.amount),
            frequency=r.frequency.value,
            next_date=r.next_date.isoformat(),
            category=cat_name,
            category_icon=cat_icon,
            is_active=r.is_active,
            auto_record=r.auto_record,
        )
        for r, cat_name, cat_icon in rows
    ]


@router.post("/recurring", response_model=RecurringItem)
async def create_recurring(
    data: RecurringCreateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        cat = await session.scalar(
            select(Category).where(
                Category.id == uuid.UUID(data.category_id),
                Category.family_id == user.family_id,
            )
        )
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

        r = RecurringPayment(
            family_id=user.family_id,
            user_id=user.id,
            category_id=uuid.UUID(data.category_id),
            name=data.name,
            amount=Decimal(str(data.amount)),
            frequency=PaymentFrequency(data.frequency),
            next_date=date.fromisoformat(data.next_date),
            auto_record=data.auto_record,
            is_active=True,
        )
        session.add(r)
        await session.commit()
        await session.refresh(r)

    return RecurringItem(
        id=str(r.id),
        name=r.name,
        amount=float(r.amount),
        frequency=r.frequency.value,
        next_date=r.next_date.isoformat(),
        category=cat.name,
        category_icon=cat.icon,
        is_active=r.is_active,
        auto_record=r.auto_record,
    )


@router.put("/recurring/{rec_id}/mark-paid")
async def mark_recurring_paid(rec_id: str, user: User = Depends(get_current_user)):
    """Record payment for this cycle and advance next_date."""
    async with async_session() as session:
        r = await session.scalar(
            select(RecurringPayment).where(
                RecurringPayment.id == uuid.UUID(rec_id),
                RecurringPayment.family_id == user.family_id,
            )
        )
        if not r:
            raise HTTPException(status_code=404, detail="Recurring payment not found")

        # Create transaction
        tx = Transaction(
            family_id=user.family_id,
            user_id=user.id,
            category_id=r.category_id,
            type=TransactionType.expense,
            amount=r.amount,
            merchant=r.name,
            description=f"Recurring: {r.name}",
            date=date.today(),
            scope=Scope.family,
            ai_confidence=Decimal("1.0"),
            meta={"source": "recurring", "recurring_id": str(r.id)},
        )
        session.add(tx)

        # Advance next_date
        freq_delta = {
            PaymentFrequency.weekly: timedelta(weeks=1),
            PaymentFrequency.monthly: timedelta(days=30),
            PaymentFrequency.quarterly: timedelta(days=90),
            PaymentFrequency.yearly: timedelta(days=365),
        }
        r.next_date = r.next_date + freq_delta.get(r.frequency, timedelta(days=30))
        await session.commit()

    return {"ok": True, "next_date": r.next_date.isoformat()}


# ---------------------------------------------------------------------------
# Life Events
# ---------------------------------------------------------------------------


@router.get("/life-events", response_model=list[LifeEventItem])
async def list_life_events(
    type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        filters = [LifeEvent.family_id == user.family_id]
        if type:
            filters.append(LifeEvent.type == LifeEventType(type))
        if date_from:
            filters.append(LifeEvent.date >= date.fromisoformat(date_from))
        if date_to:
            filters.append(LifeEvent.date <= date.fromisoformat(date_to))

        rows = (
            (
                await session.execute(
                    select(LifeEvent)
                    .where(*filters)
                    .order_by(desc(LifeEvent.date), desc(LifeEvent.created_at))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    return [
        LifeEventItem(
            id=str(e.id),
            type=e.type.value,
            date=e.date.isoformat(),
            text=e.text,
            tags=e.tags,
            data=e.data,
            created_at=e.created_at.isoformat(),
        )
        for e in rows
    ]


@router.post("/life-events", response_model=LifeEventItem)
async def create_life_event(
    data: LifeEventCreateRequest,
    user: User = Depends(get_current_user),
):
    event_date = date.fromisoformat(data.date) if data.date else date.today()
    async with async_session() as session:
        e = LifeEvent(
            family_id=user.family_id,
            user_id=user.id,
            type=LifeEventType(data.type),
            date=event_date,
            text=data.text,
            tags=data.tags,
            data=data.data,
        )
        session.add(e)
        await session.commit()
        await session.refresh(e)

    return LifeEventItem(
        id=str(e.id),
        type=e.type.value,
        date=e.date.isoformat(),
        text=e.text,
        tags=e.tags,
        data=e.data,
        created_at=e.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskItem])
async def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        filters = [Task.family_id == user.family_id]
        if status:
            filters.append(Task.status == TaskStatus(status))
        if priority:
            filters.append(Task.priority == TaskPriority(priority))

        rows = (
            (
                await session.execute(
                    select(Task)
                    .where(*filters)
                    .order_by(
                        asc(Task.status),
                        desc(Task.priority),
                        asc(Task.due_at),
                    )
                )
            )
            .scalars()
            .all()
        )

    return [
        TaskItem(
            id=str(t.id),
            title=t.title,
            description=t.description,
            status=t.status.value,
            priority=t.priority.value,
            due_at=t.due_at.isoformat() if t.due_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in rows
    ]


@router.post("/tasks", response_model=TaskItem)
async def create_task(
    data: TaskCreateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        due = None
        if data.due_at:
            due = datetime.fromisoformat(data.due_at).replace(tzinfo=UTC)
        t = Task(
            family_id=user.family_id,
            user_id=user.id,
            title=data.title,
            description=data.description,
            priority=TaskPriority(data.priority),
            due_at=due,
            status=TaskStatus.pending,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

    return TaskItem(
        id=str(t.id),
        title=t.title,
        description=t.description,
        status=t.status.value,
        priority=t.priority.value,
        due_at=t.due_at.isoformat() if t.due_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
    )


@router.put("/tasks/{task_id}", response_model=TaskItem)
async def update_task(
    task_id: str,
    data: TaskUpdateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        t = await session.scalar(
            select(Task).where(
                Task.id == uuid.UUID(task_id),
                Task.family_id == user.family_id,
            )
        )
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")

        if data.status is not None:
            t.status = TaskStatus(data.status)
            if data.status == "done":
                t.completed_at = datetime.now(UTC)
        if data.priority is not None:
            t.priority = TaskPriority(data.priority)
        if data.title is not None:
            t.title = data.title
        if data.description is not None:
            t.description = data.description
        if data.due_at is not None:
            t.due_at = datetime.fromisoformat(data.due_at).replace(tzinfo=UTC)

        await session.commit()
        await session.refresh(t)

    return TaskItem(
        id=str(t.id),
        title=t.title,
        description=t.description,
        status=t.status.value,
        priority=t.priority.value,
        due_at=t.due_at.isoformat() if t.due_at else None,
        completed_at=t.completed_at.isoformat() if t.completed_at else None,
    )


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: User = Depends(get_current_user)):
    async with async_session() as session:
        t = await session.scalar(
            select(Task).where(
                Task.id == uuid.UUID(task_id),
                Task.family_id == user.family_id,
            )
        )
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        await session.delete(t)
        await session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.get("/export/csv")
async def export_csv(
    date_from: str | None = None,
    date_to: str | None = None,
    user: User = Depends(get_current_user),
):
    """Export all transactions as CSV."""
    async with async_session() as session:
        filters = [Transaction.family_id == user.family_id]
        if date_from:
            filters.append(Transaction.date >= date.fromisoformat(date_from))
        if date_to:
            filters.append(Transaction.date <= date.fromisoformat(date_to))

        rows = (
            await session.execute(
                select(Transaction, Category.name.label("cat_name"))
                .join(Category, Transaction.category_id == Category.id)
                .where(*filters)
                .order_by(desc(Transaction.date))
            )
        ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Amount", "Category", "Merchant", "Description", "Scope"])
    for tx, cat_name in rows:
        writer.writerow(
            [
                tx.date.isoformat(),
                tx.type.value,
                float(tx.amount),
                cat_name,
                tx.merchant or "",
                tx.description or "",
                tx.scope.value,
            ]
        )

    output.seek(0)
    filename = f"transactions_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Settings (kept + GET added)
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: User = Depends(get_current_user)):
    async with async_session() as session:
        fam = await session.scalar(select(Family).where(Family.id == user.family_id))
        cats = (
            (await session.execute(select(Category).where(Category.family_id == user.family_id)))
            .scalars()
            .all()
        )
    return SettingsResponse(
        language=user.language,
        currency=fam.currency if fam else "USD",
        business_type=user.business_type,
        categories=[
            {"id": str(c.id), "name": c.name, "icon": c.icon, "scope": c.scope.value} for c in cats
        ],
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        db_user = await session.scalar(select(User).where(User.id == user.id))
        fam = await session.scalar(select(Family).where(Family.id == db_user.family_id))

        if data.language:
            db_user.language = data.language
        if data.currency and fam:
            fam.currency = data.currency

        await session.commit()

        cats = (
            (await session.execute(select(Category).where(Category.family_id == db_user.family_id)))
            .scalars()
            .all()
        )

    return SettingsResponse(
        language=db_user.language,
        currency=fam.currency if fam else "USD",
        business_type=db_user.business_type,
        categories=[
            {"id": str(c.id), "name": c.name, "icon": c.icon, "scope": c.scope.value} for c in cats
        ],
    )
