"""Mini App REST API — endpoints for Telegram WebView SPA."""

import csv
import io
import ipaddress
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, select

from api.webapp_auth import validate_webapp_data
from src.core.access import (
    apply_scope_filter,
    apply_visibility_filter,
    can_access_scope,
    get_default_visibility,
)
from src.core.config import settings
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
from src.core.models.tracker import Tracker, TrackerEntry
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["miniapp"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_enum(enum_cls, value: str, field_name: str):
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=400, detail=f"Invalid {field_name}: {value}"
        )


def _require_owner(user: User):
    if user.role.value != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")


async def _check_permission(user: User, permission: str, session=None):
    """Check if user has a specific permission. Owner always passes."""
    if user.role.value == "owner":
        return
    # For non-owner, load membership permissions
    from src.core.models.workspace_membership import WorkspaceMembership

    if session is None:
        async with async_session() as s:
            membership = await s.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.family_id == user.family_id,
                    WorkspaceMembership.status == "active",
                )
            )
    else:
        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.family_id == user.family_id,
                WorkspaceMembership.status == "active",
            )
        )
    if membership and permission in (membership.permissions or []):
        return
    raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")


def _ensure_scope_allowed(user: User, scope: Scope) -> None:
    if not can_access_scope(user.role.value, scope):
        raise HTTPException(status_code=403, detail="Scope access denied")


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_global
    except ValueError:
        return False


def _month_offset(base: date, months_back: int) -> date:
    m = base.month - months_back
    y = base.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, 1)


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400, detail=f"Invalid UUID for {field_name}: {value}"
        )


def _apply_tx_filter(stmt, user: User):
    """Apply visibility filter for Transaction queries in miniapp."""
    return apply_visibility_filter(stmt, Transaction, user.role.value, str(user.id))


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


class TimezoneDetectRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=100)


class UserProfile(BaseModel):
    id: str
    name: str
    role: str
    language: str
    currency: str
    business_type: str | None
    family_id: str
    family_name: str
    invite_code: str | None


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


class MemberItem(BaseModel):
    id: str
    user_id: str
    user_name: str | None
    membership_type: str
    role: str
    permissions: list[str]
    status: str
    joined_at: str | None


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
        fam = await session.scalar(
            select(Family).where(Family.id == user.family_id)
        )
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
            invite_code=fam.invite_code if user.role.value == "owner" else None,
        )


@router.get("/family/invite-code")
async def get_invite_code(user: User = Depends(get_current_user)):
    """Get family invite code (owner only)."""
    _require_owner(user)
    async with async_session() as session:
        fam = await session.scalar(
            select(Family).where(Family.id == user.family_id)
        )
        if not fam:
            raise HTTPException(status_code=404, detail="Family not found")
        return {"invite_code": fam.invite_code, "family_name": fam.name}


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryItem])
async def list_categories(user: User = Depends(get_current_user)):
    """List all categories visible to the user."""
    async with async_session() as session:
        stmt = (
            select(Category)
            .where(Category.family_id == user.family_id)
            .order_by(Category.scope, Category.name)
        )
        result = await session.execute(apply_scope_filter(stmt, Category, user.role.value))
        cats = result.scalars().all()
        return [
            CategoryItem(
                id=str(c.id), name=c.name,
                icon=c.icon, scope=c.scope.value,
            )
            for c in cats
        ]


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
        exp_stmt = (
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
        exp_result = await session.execute(
            _apply_tx_filter(exp_stmt, user)
        )
        expense_rows = exp_result.all()
        total_expense = sum(float(r[3]) for r in expense_rows)

        # Income by category
        inc_stmt = (
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
        inc_result = await session.execute(
            _apply_tx_filter(inc_stmt, user)
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
            month_date = _month_offset(today, i)
            if month_date.month == 12:
                end = month_date.replace(year=month_date.year + 1, month=1, day=1)
            else:
                end = month_date.replace(month=month_date.month + 1, day=1)

            exp_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == user.family_id,
                Transaction.date >= month_date,
                Transaction.date < end,
                Transaction.type == TransactionType.expense,
            )
            exp = await session.scalar(_apply_tx_filter(exp_stmt, user))
            inc_stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == user.family_id,
                Transaction.date >= month_date,
                Transaction.date < end,
                Transaction.type == TransactionType.income,
            )
            inc = await session.scalar(_apply_tx_filter(inc_stmt, user))
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
            base_filter.append(
                Transaction.type == _parse_enum(
                    TransactionType, type, "type"
                )
            )
        if category_id:
            base_filter.append(
                Transaction.category_id == _parse_uuid(
                    category_id, "category_id"
                )
            )
        if date_from:
            base_filter.append(
                Transaction.date >= date.fromisoformat(date_from)
            )
        if date_to:
            base_filter.append(
                Transaction.date <= date.fromisoformat(date_to)
            )
        if search:
            escaped = _escape_like(search)
            base_filter.append(
                Transaction.merchant.ilike(
                    f"%{escaped}%", escape="\\"
                )
                | Transaction.description.ilike(
                    f"%{escaped}%", escape="\\"
                )
            )

        total_stmt = select(func.count(Transaction.id)).where(*base_filter)
        total = (
            await session.scalar(_apply_tx_filter(total_stmt, user))
        ) or 0

        query = _apply_tx_filter(
            select(Transaction, Category.name.label("cat_name"), Category.id.label("cat_id"))
            .join(Category, Transaction.category_id == Category.id)
            .where(*base_filter)
            .order_by(desc(Transaction.date), desc(Transaction.created_at))
            .offset((page - 1) * per_page)
            .limit(per_page),
            user,
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
    tx_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        stmt = (
            select(Transaction, Category.name, Category.id)
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.id == tx_id,
                Transaction.family_id == user.family_id,
            )
        )
        row = (
            await session.execute(_apply_tx_filter(stmt, user))
        ).first()
        if not row:
            raise HTTPException(
                status_code=404, detail="Transaction not found"
            )
        tx, cat_name, cat_id = row
        return _tx_to_item(tx, cat_name, str(cat_id))


@router.post("/transactions", response_model=TransactionItem)
async def create_transaction(
    data: TransactionCreateRequest,
    user: User = Depends(get_current_user),
):
    tx_date = date.fromisoformat(data.date) if data.date else date.today()
    tx_type = _parse_enum(TransactionType, data.type, "type")
    cat_id = _parse_uuid(data.category_id, "category_id")

    async with async_session() as session:
        await _check_permission(user, "create_finance", session)
        cat_stmt = select(Category).where(
                Category.id == cat_id,
                Category.family_id == user.family_id,
            )
        cat = await session.scalar(apply_scope_filter(cat_stmt, Category, user.role.value))
        if not cat:
            raise HTTPException(
                status_code=404, detail="Category not found"
            )

        tx = Transaction(
            family_id=user.family_id,
            user_id=user.id,
            category_id=cat_id,
            type=tx_type,
            amount=Decimal(str(data.amount)),
            merchant=data.merchant,
            description=data.description,
            date=tx_date,
            scope=cat.scope,
            visibility=get_default_visibility(cat.scope).value,
            ai_confidence=Decimal("1.0"),
            meta={"source": "miniapp"},
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        return _tx_to_item(tx, cat.name, str(cat.id))


@router.put("/transactions/{tx_id}", response_model=TransactionItem)
async def update_transaction(
    tx_id: uuid.UUID,
    data: TransactionUpdateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        await _check_permission(user, "edit_finance", session)
        tx_stmt = select(Transaction).where(
                Transaction.id == tx_id,
                Transaction.family_id == user.family_id,
            )
        tx = await session.scalar(_apply_tx_filter(tx_stmt, user))
        if not tx:
            raise HTTPException(
                status_code=404, detail="Transaction not found"
            )

        if data.amount is not None:
            tx.amount = Decimal(str(data.amount))
        if data.category_id is not None:
            new_cat_id = _parse_uuid(
                data.category_id, "category_id"
            )
            cat_stmt = select(Category).where(
                    Category.id == new_cat_id,
                    Category.family_id == user.family_id,
                )
            cat_check = await session.scalar(
                apply_scope_filter(cat_stmt, Category, user.role.value)
            )
            if not cat_check:
                raise HTTPException(
                    status_code=404, detail="Category not found"
                )
            tx.category_id = new_cat_id
            tx.scope = cat_check.scope
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
    tx_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        await _check_permission(user, "delete_finance", session)
        stmt = select(Transaction).where(
                Transaction.id == tx_id,
                Transaction.family_id == user.family_id,
            )
        tx = await session.scalar(_apply_tx_filter(stmt, user))
        if not tx:
            raise HTTPException(
                status_code=404, detail="Transaction not found"
            )
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
        query = (
            select(Budget, Category.name, Category.icon)
            .outerjoin(Category, Budget.category_id == Category.id)
            .where(
                Budget.family_id == user.family_id,
                Budget.is_active == True,  # noqa: E712
            )
            .order_by(Budget.period, Budget.created_at)
        )
        rows = (await session.execute(apply_scope_filter(query, Budget, user.role.value))).all()

        result = []
        for b, cat_name, cat_icon in rows:
            start = (
                week_start
                if b.period == BudgetPeriod.weekly
                else month_start
            )

            spent_filter = [
                Transaction.family_id == user.family_id,
                Transaction.date >= start,
                Transaction.type == TransactionType.expense,
            ]
            if b.category_id:
                spent_filter.append(
                    Transaction.category_id == b.category_id
                )

            spent_stmt = select(func.sum(Transaction.amount)).where(*spent_filter)
            spent = float(
                await session.scalar(
                    _apply_tx_filter(spent_stmt, user)
                )
                or 0
            )

            budget_amount = float(b.amount)
            result.append(
                BudgetItem(
                    id=str(b.id),
                    category_id=(
                        str(b.category_id) if b.category_id else None
                    ),
                    category_name=cat_name,
                    category_icon=cat_icon,
                    scope=b.scope.value,
                    amount=budget_amount,
                    period=b.period.value,
                    alert_at=float(b.alert_at),
                    is_active=b.is_active,
                    spent=spent,
                    percent=(
                        (spent / budget_amount * 100)
                        if budget_amount > 0
                        else 0
                    ),
                )
            )
        return result


@router.post("/budgets", response_model=BudgetItem)
async def create_budget(
    data: BudgetCreateRequest,
    user: User = Depends(get_current_user),
):
    scope = _parse_enum(Scope, data.scope, "scope")
    _ensure_scope_allowed(user, scope)
    period = _parse_enum(BudgetPeriod, data.period, "period")
    cat_id = (
        _parse_uuid(data.category_id, "category_id")
        if data.category_id
        else None
    )

    async with async_session() as session:
        await _check_permission(user, "manage_budgets", session)
        if cat_id:
            cat_stmt = select(Category).where(
                Category.id == cat_id,
                Category.family_id == user.family_id,
            )
            cat = await session.scalar(apply_scope_filter(cat_stmt, Category, user.role.value))
            if not cat:
                raise HTTPException(status_code=404, detail="Category not found")
            if cat.scope != scope:
                raise HTTPException(
                    status_code=400,
                    detail="Budget scope must match category scope",
                )
        b = Budget(
            family_id=user.family_id,
            category_id=cat_id,
            scope=scope,
            amount=Decimal(str(data.amount)),
            period=period,
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
async def delete_budget(
    budget_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        await _check_permission(user, "manage_budgets", session)
        b = await session.scalar(
            apply_scope_filter(
                select(Budget).where(
                    Budget.id == budget_id,
                    Budget.family_id == user.family_id,
                ),
                Budget,
                user.role.value,
            )
        )
        if not b:
            raise HTTPException(
                status_code=404, detail="Budget not found"
            )
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
                apply_scope_filter(
                    select(
                    RecurringPayment, Category.name, Category.icon
                )
                .join(
                    Category,
                    RecurringPayment.category_id == Category.id,
                )
                .where(
                    RecurringPayment.family_id == user.family_id,
                    RecurringPayment.is_active == True,  # noqa: E712
                )
                .order_by(asc(RecurringPayment.next_date)),
                    Category,
                    user.role.value,
                )
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
    cat_id = _parse_uuid(data.category_id, "category_id")
    freq = _parse_enum(PaymentFrequency, data.frequency, "frequency")

    async with async_session() as session:
        await _check_permission(user, "create_finance", session)
        cat_stmt = select(Category).where(
                Category.id == cat_id,
                Category.family_id == user.family_id,
            )
        cat = await session.scalar(apply_scope_filter(cat_stmt, Category, user.role.value))
        if not cat:
            raise HTTPException(
                status_code=404, detail="Category not found"
            )

        r = RecurringPayment(
            family_id=user.family_id,
            user_id=user.id,
            category_id=cat_id,
            name=data.name,
            amount=Decimal(str(data.amount)),
            frequency=freq,
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
async def mark_recurring_paid(
    rec_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    """Record payment for this cycle and advance next_date."""
    async with async_session() as session:
        await _check_permission(user, "create_finance", session)
        row = (
            await session.execute(
                apply_scope_filter(
                    select(RecurringPayment, Category.scope)
                    .join(Category, RecurringPayment.category_id == Category.id)
                    .where(
                RecurringPayment.id == rec_id,
                RecurringPayment.family_id == user.family_id,
                    ),
                    Category,
                    user.role.value,
                )
            )
        )
        row = row.first()
        if not row:
            raise HTTPException(status_code=404, detail="Recurring payment not found")
        r, recurring_scope = row

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
            scope=recurring_scope,
            visibility=get_default_visibility(recurring_scope).value,
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
        next_date_str = r.next_date.isoformat()

    return {"ok": True, "next_date": next_date_str}


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
        # Life events are strictly private — filtered by user_id
        filters = [
            LifeEvent.family_id == user.family_id,
            LifeEvent.user_id == user.id,
        ]
        if type:
            filters.append(
                LifeEvent.type == _parse_enum(
                    LifeEventType, type, "type"
                )
            )
        if date_from:
            filters.append(LifeEvent.date >= date.fromisoformat(date_from))
        if date_to:
            filters.append(LifeEvent.date <= date.fromisoformat(date_to))

        rows = (
            (
                await session.execute(
                    select(LifeEvent)
                    .where(*filters)
                    .order_by(
                        desc(LifeEvent.date),
                        desc(LifeEvent.created_at),
                    )
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
    event_date = (
        date.fromisoformat(data.date) if data.date else date.today()
    )
    event_type = _parse_enum(LifeEventType, data.type, "type")
    async with async_session() as session:
        e = LifeEvent(
            family_id=user.family_id,
            user_id=user.id,
            type=event_type,
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
        # Tasks filtered by user_id — private by default, visibility filter not needed
        filters = [
            Task.family_id == user.family_id,
            Task.user_id == user.id,
        ]
        if status:
            filters.append(
                Task.status == _parse_enum(
                    TaskStatus, status, "status"
                )
            )
        if priority:
            filters.append(
                Task.priority == _parse_enum(
                    TaskPriority, priority, "priority"
                )
            )

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
                due_at=(
                    t.due_at.isoformat() if t.due_at else None
                ),
                completed_at=(
                    t.completed_at.isoformat()
                    if t.completed_at
                    else None
                ),
            )
            for t in rows
        ]


@router.post("/tasks", response_model=TaskItem)
async def create_task(
    data: TaskCreateRequest,
    user: User = Depends(get_current_user),
):
    task_priority = _parse_enum(TaskPriority, data.priority, "priority")
    async with async_session() as session:
        due = None
        if data.due_at:
            due = datetime.fromisoformat(data.due_at).replace(
                tzinfo=UTC
            )
        t = Task(
            family_id=user.family_id,
            user_id=user.id,
            title=data.title,
            description=data.description,
            priority=task_priority,
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
            due_at=(
                t.due_at.isoformat() if t.due_at else None
            ),
            completed_at=(
                t.completed_at.isoformat()
                if t.completed_at
                else None
            ),
        )


@router.put("/tasks/{task_id}", response_model=TaskItem)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdateRequest,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        t = await session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.family_id == user.family_id,
                Task.user_id == user.id,
            )
        )
        if not t:
            raise HTTPException(
                status_code=404, detail="Task not found"
            )

        if data.status is not None:
            t.status = _parse_enum(
                TaskStatus, data.status, "status"
            )
            if data.status == "done":
                t.completed_at = datetime.now(UTC)
        if data.priority is not None:
            t.priority = _parse_enum(
                TaskPriority, data.priority, "priority"
            )
        if data.title is not None:
            t.title = data.title
        if data.description is not None:
            t.description = data.description
        if data.due_at is not None:
            t.due_at = datetime.fromisoformat(
                data.due_at
            ).replace(tzinfo=UTC)

        await session.commit()
        await session.refresh(t)
        return TaskItem(
            id=str(t.id),
            title=t.title,
            description=t.description,
            status=t.status.value,
            priority=t.priority.value,
            due_at=(
                t.due_at.isoformat() if t.due_at else None
            ),
            completed_at=(
                t.completed_at.isoformat()
                if t.completed_at
                else None
            ),
        )


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    async with async_session() as session:
        t = await session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.family_id == user.family_id,
                Task.user_id == user.id,
            )
        )
        if not t:
            raise HTTPException(
                status_code=404, detail="Task not found"
            )
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
        await _check_permission(user, "view_reports", session)
        filters = [Transaction.family_id == user.family_id]
        if date_from:
            filters.append(Transaction.date >= date.fromisoformat(date_from))
        if date_to:
            filters.append(Transaction.date <= date.fromisoformat(date_to))

        stmt = (
                select(
                    Transaction, Category.name.label("cat_name")
                )
                .join(
                    Category,
                    Transaction.category_id == Category.id,
                )
                .where(*filters)
                .order_by(desc(Transaction.date))
                .limit(10000)
            )
        rows = (
            await session.execute(_apply_tx_filter(stmt, user))
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
# Members
# ---------------------------------------------------------------------------


@router.get("/family/members", response_model=list[MemberItem])
async def list_members(user: User = Depends(get_current_user)):
    """List all family members with their roles."""
    from src.core.models.workspace_membership import WorkspaceMembership

    async with async_session() as session:
        stmt = (
            select(WorkspaceMembership, User.name)
            .join(User, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.family_id == user.family_id,
                WorkspaceMembership.status.in_(["active", "invited"]),
            )
            .order_by(WorkspaceMembership.role)
        )
        rows = (await session.execute(stmt)).all()

    is_owner = user.role and user.role.value == "owner"
    return [
        MemberItem(
            id=str(m.id),
            user_id=str(m.user_id),
            user_name=name,
            membership_type=m.membership_type.value if m.membership_type else "family",
            role=m.role.value if m.role else "member",
            permissions=(m.permissions or []) if is_owner else [],
            status=m.status.value if m.status else "active",
            joined_at=m.joined_at.isoformat() if m.joined_at else None,
        )
        for m, name in rows
    ]


class MemberRoleUpdateRequest(BaseModel):
    role: str


@router.put("/family/members/{member_id}/role")
async def update_member_role(
    member_id: uuid.UUID,
    data: MemberRoleUpdateRequest,
    user: User = Depends(get_current_user),
):
    """Update a member's role. Owner or manage_members permission required."""
    from src.core.models.workspace_membership import ROLE_PRESETS, WorkspaceMembership

    async with async_session() as session:
        await _check_permission(user, "manage_members", session)

        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == member_id,
                WorkspaceMembership.family_id == user.family_id,
            )
        )
        if not membership:
            raise HTTPException(status_code=404, detail="Member not found")

        # Cannot change owner's role
        if membership.role and membership.role.value == "owner":
            raise HTTPException(status_code=403, detail="Cannot change owner role")

        new_role = data.role
        if not new_role or new_role not in ROLE_PRESETS:
            raise HTTPException(status_code=400, detail=f"Invalid role: {new_role}")

        if new_role == "owner":
            raise HTTPException(status_code=403, detail="Cannot assign owner role")

        from src.core.models.enums import MembershipRole

        membership.role = MembershipRole(new_role)
        membership.permissions = ROLE_PRESETS[new_role]

        # Audit log
        from src.core.audit import log_action

        await log_action(
            session=session,
            family_id=str(user.family_id),
            user_id=str(user.id),
            action="update",
            entity_type="workspace_membership",
            entity_id=str(membership.id),
            new_data={"role": new_role, "permissions": ROLE_PRESETS[new_role]},
        )

        await session.commit()
        return {"ok": True, "role": new_role, "permissions": ROLE_PRESETS[new_role]}


@router.put("/family/members/{member_id}/suspend")
async def suspend_member(
    member_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    """Suspend a member's access."""
    from src.core.models.workspace_membership import WorkspaceMembership

    async with async_session() as session:
        await _check_permission(user, "manage_members", session)

        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == member_id,
                WorkspaceMembership.family_id == user.family_id,
            )
        )
        if not membership:
            raise HTTPException(status_code=404, detail="Member not found")
        if membership.role and membership.role.value == "owner":
            raise HTTPException(status_code=403, detail="Cannot suspend owner")

        from src.core.models.enums import MembershipStatus

        membership.status = MembershipStatus.suspended

        from src.core.audit import log_action

        await log_action(
            session=session,
            family_id=str(user.family_id),
            user_id=str(user.id),
            action="update",
            entity_type="workspace_membership",
            entity_id=str(membership.id),
            new_data={"status": "suspended"},
        )

        await session.commit()
        return {"ok": True}


@router.put("/family/members/{member_id}/activate")
async def activate_member(
    member_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    """Reactivate a suspended member."""
    from src.core.models.workspace_membership import WorkspaceMembership

    async with async_session() as session:
        await _check_permission(user, "manage_members", session)

        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == member_id,
                WorkspaceMembership.family_id == user.family_id,
            )
        )
        if not membership:
            raise HTTPException(status_code=404, detail="Member not found")

        from src.core.models.enums import MembershipStatus

        membership.status = MembershipStatus.active

        from src.core.audit import log_action

        await log_action(
            session=session,
            family_id=str(user.family_id),
            user_id=str(user.id),
            action="update",
            entity_type="workspace_membership",
            entity_id=str(membership.id),
            new_data={"status": "active"},
        )

        await session.commit()
        return {"ok": True}


@router.delete("/family/members/{member_id}")
async def remove_member(
    member_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    """Remove a member from the family."""
    from src.core.models.workspace_membership import WorkspaceMembership

    async with async_session() as session:
        await _check_permission(user, "manage_members", session)

        membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.id == member_id,
                WorkspaceMembership.family_id == user.family_id,
            )
        )
        if not membership:
            raise HTTPException(status_code=404, detail="Member not found")
        if membership.role and membership.role.value == "owner":
            raise HTTPException(status_code=403, detail="Cannot remove owner")

        from src.core.models.enums import MembershipStatus

        membership.status = MembershipStatus.revoked

        from src.core.audit import log_action

        await log_action(
            session=session,
            family_id=str(user.family_id),
            user_id=str(user.id),
            action="delete",
            entity_type="workspace_membership",
            entity_id=str(membership.id),
            new_data={"status": "revoked"},
        )

        await session.commit()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Settings (kept + GET added)
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: User = Depends(get_current_user)):
    async with async_session() as session:
        fam = await session.scalar(
            select(Family).where(Family.id == user.family_id)
        )
        cats = (
            (
                await session.execute(
                    apply_scope_filter(
                        select(Category).where(
                            Category.family_id == user.family_id
                        ),
                        Category,
                        user.role.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        return SettingsResponse(
            language=user.language,
            currency=fam.currency if fam else "USD",
            business_type=user.business_type,
            categories=[
                {
                    "id": str(c.id),
                    "name": c.name,
                    "icon": c.icon,
                    "scope": c.scope.value,
                }
                for c in cats
            ],
        )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
):
    if data.currency:
        _require_owner(user)

    from src.core.models.user_profile import UserProfile as UserProfileModel

    async with async_session() as session:
        db_user = await session.scalar(
            select(User).where(User.id == user.id)
        )
        fam = await session.scalar(
            select(Family).where(Family.id == db_user.family_id)
        )
        profile = await session.scalar(
            select(UserProfileModel).where(UserProfileModel.user_id == db_user.id).limit(1)
        )

        if data.language:
            db_user.language = data.language
            if profile:
                profile.preferred_language = data.language
                if settings.ff_locale_v2_write:
                    profile.notification_language = data.language
                    from datetime import datetime

                    profile.locale_updated_at = datetime.now(UTC)
        if data.currency and fam:
            fam.currency = data.currency

        await session.commit()

        cats = (
            (
                await session.execute(
                    apply_scope_filter(
                        select(Category).where(
                            Category.family_id == db_user.family_id
                        ),
                        Category,
                        user.role.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        return SettingsResponse(
            language=db_user.language,
            currency=fam.currency if fam else "USD",
            business_type=db_user.business_type,
            categories=[
                {
                    "id": str(c.id),
                    "name": c.name,
                    "icon": c.icon,
                    "scope": c.scope.value,
                }
                for c in cats
            ],
        )


# ---------------------------------------------------------------------------
# Browser timezone detection (Intl.DateTimeFormat)
# ---------------------------------------------------------------------------


@router.post("/tz/detect")
async def detect_timezone_from_js(
    data: TimezoneDetectRequest,
    user: User = Depends(get_current_user),
):
    """Save timezone detected by the browser's Intl.DateTimeFormat API."""
    from src.core.timezone import maybe_update_timezone, validate_timezone

    tz = data.timezone
    if not validate_timezone(tz):
        raise HTTPException(status_code=400, detail="Invalid timezone")

    updated = await maybe_update_timezone(
        user_id=str(user.id),
        timezone=tz,
        source="mini_app_js",
    )
    return {"ok": True, "updated": updated, "timezone": tz}


# ---------------------------------------------------------------------------
# IP Geolocation
# ---------------------------------------------------------------------------


@router.post("/geo/detect")
async def detect_geo_from_ip(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Detect user's city/timezone from IP and save to profile."""
    import httpx

    from src.core.models.user_profile import UserProfile as UserProfileModel

    # Get client IP (handle proxies / Railway)
    client_ip = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "")
    if not client_ip and request.client:
        client_ip = request.client.host

    if not client_ip or not _is_public_ip(client_ip):
        return {"ok": False, "reason": "invalid_ip"}

    # Call ip-api.com (free, no key, 45 req/min)
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"http://ip-api.com/json/{client_ip}",
                params={"fields": "status,city,regionName,country,timezone,lat,lon"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("IP geolocation API failed: %s", e)
        return {"ok": False, "reason": "geo_api_error"}

    if data.get("status") != "success":
        return {"ok": False, "reason": "geo_lookup_failed"}

    city = data.get("city")
    timezone = data.get("timezone")

    if not city:
        return {"ok": False, "reason": "no_city"}

    # Save to user profile (only if not already set)
    async with async_session() as session:
        profile = await session.scalar(
            select(UserProfileModel).where(UserProfileModel.user_id == user.id)
        )
        if profile:
            changed = False
            if not profile.city:
                profile.city = city
                changed = True
            # Only overwrite timezone from geo if current source is lower confidence
            _upgradeable = {"default", "channel_hint", "", None}
            if timezone and profile.timezone_source in _upgradeable:
                profile.timezone = timezone
                profile.timezone_source = "geo_ip"
                profile.timezone_confidence = 70
                from datetime import datetime

                profile.locale_updated_at = datetime.now(UTC)
                changed = True
            if changed:
                await session.commit()
        else:
            profile = UserProfileModel(
                user_id=user.id,
                family_id=user.family_id,
                display_name=user.name,
                timezone=timezone or "UTC",
                timezone_source="geo_ip" if timezone else "default",
                timezone_confidence=70 if timezone else 0,
                city=city,
                preferred_language=user.language,
            )
            session.add(profile)
            await session.commit()

    return {
        "ok": True,
        "city": city,
        "timezone": timezone,
        "region": data.get("regionName"),
        "country": data.get("country"),
    }


# ---------------------------------------------------------------------------
# Trackers
# ---------------------------------------------------------------------------

_TRACKER_DEFAULTS: dict[str, dict] = {
    # value_mode:
    #   "boolean" → habit/medication — log done/not-done, stats show day streak
    #   "single"  → mood/weight/sleep — one value per day (last write wins), show last value + 7d avg
    #   "sum"     → water/nutrition/gratitude/workout/custom — accumulate all logs per day, show daily total
    "mood":       {"emoji": "😊", "goal": 10,   "unit": "/ 10",   "scale": [1, 10], "value_mode": "single"},
    "habit":      {"emoji": "🔥", "goal": 1,    "unit": "",        "scale": None,    "value_mode": "boolean"},
    "water":      {"emoji": "💧", "goal": 8,    "unit": "glasses", "scale": None,    "value_mode": "sum"},
    "sleep":      {"emoji": "🌙", "goal": 8,    "unit": "h",       "scale": None,    "value_mode": "single"},
    "weight":     {"emoji": "⚖️", "goal": None, "unit": "kg",      "scale": None,    "value_mode": "single"},
    "workout":    {"emoji": "💪", "goal": 1,    "unit": "sessions","scale": None,    "value_mode": "sum"},
    "nutrition":  {"emoji": "🥗", "goal": 2000, "unit": "kcal",    "scale": None,    "value_mode": "sum"},
    "gratitude":  {"emoji": "🙏", "goal": 3,    "unit": "items",   "scale": None,    "value_mode": "sum"},
    "medication": {"emoji": "💊", "goal": 1,    "unit": "dose",    "scale": None,    "value_mode": "boolean"},
    "custom":     {"emoji": "✨", "goal": 1,    "unit": "times",   "scale": None,    "value_mode": "sum"},
}


class TrackerCreate(BaseModel):
    tracker_type: str = Field(..., max_length=32)
    name: str = Field(..., max_length=128)
    emoji: str | None = Field(None, max_length=8)
    description: str | None = None
    config: dict | None = None


class TrackerUpdate(BaseModel):
    name: str | None = Field(None, max_length=128)
    emoji: str | None = Field(None, max_length=8)
    description: str | None = None
    config: dict | None = None


class TrackerEntryCreate(BaseModel):
    date: str  # ISO date YYYY-MM-DD
    value: int | None = None
    data: dict | None = None
    note: str | None = None


def _tracker_json(
    t: Tracker,
    streak: int = 0,
    today_done: bool = False,
    today_total: int = 0,
    today_value: int | None = None,
) -> dict:
    defaults = _TRACKER_DEFAULTS.get(t.tracker_type, {})
    config = {**defaults, **(t.config or {})}
    return {
        "id": str(t.id),
        "tracker_type": t.tracker_type,
        "name": t.name,
        "emoji": t.emoji or defaults.get("emoji", "📊"),
        "description": t.description,
        "config": config,
        "value_mode": config.get("value_mode", "sum"),
        "is_active": t.is_active,
        "streak": streak,
        "today_done": today_done,
        "today_total": today_total,       # sum mode: accumulated value today
        "today_value": today_value,       # single mode: last logged value today
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _entry_json(e: TrackerEntry) -> dict:
    return {
        "id": str(e.id),
        "tracker_id": str(e.tracker_id),
        "date": e.date.isoformat(),
        "value": e.value,
        "data": e.data,
        "note": e.note,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/trackers")
async def list_trackers(user: User = Depends(get_current_user)) -> list[dict]:
    """List all active trackers for the current user."""
    today = date.today()
    async with async_session() as session:
        stmt = (
            select(Tracker)
            .where(Tracker.family_id == user.family_id, Tracker.user_id == user.id, Tracker.is_active == True)
            .order_by(Tracker.created_at)
        )
        trackers = (await session.scalars(stmt)).all()

        result = []
        for t in trackers:
            # Streak: count consecutive days with at least one entry going back from today
            streak = 0
            check_date = today
            while True:
                exists = await session.scalar(
                    select(TrackerEntry.id).where(
                        TrackerEntry.tracker_id == t.id,
                        TrackerEntry.date == check_date,
                    ).limit(1)
                )
                if not exists:
                    break
                streak += 1
                check_date = check_date.replace(day=check_date.day - 1) if check_date.day > 1 else (
                    check_date.replace(month=check_date.month - 1, day=28) if check_date.month > 1
                    else check_date.replace(year=check_date.year - 1, month=12, day=31)
                )

            # Today's entries for value_mode logic
            today_entries = (await session.scalars(
                select(TrackerEntry).where(
                    TrackerEntry.tracker_id == t.id,
                    TrackerEntry.date == today,
                ).order_by(TrackerEntry.created_at)
            )).all()

            today_done = len(today_entries) > 0
            today_total = sum(e.value or 0 for e in today_entries)
            today_value = today_entries[-1].value if today_entries else None

            result.append(_tracker_json(
                t, streak=streak,
                today_done=today_done,
                today_total=today_total,
                today_value=today_value,
            ))
    return result


@router.post("/trackers")
async def create_tracker(
    body: TrackerCreate,
    user: User = Depends(get_current_user),
) -> dict:
    """Create a new tracker."""
    defaults = _TRACKER_DEFAULTS.get(body.tracker_type, {})
    config = {**defaults, **(body.config or {})}
    tracker = Tracker(
        family_id=user.family_id,
        user_id=user.id,
        tracker_type=body.tracker_type,
        name=body.name,
        emoji=body.emoji or defaults.get("emoji"),
        description=body.description,
        config=config,
    )
    async with async_session() as session:
        session.add(tracker)
        await session.commit()
        await session.refresh(tracker)
    return _tracker_json(tracker)


@router.put("/trackers/{tracker_id}")
async def update_tracker(
    tracker_id: str,
    body: TrackerUpdate,
    user: User = Depends(get_current_user),
) -> dict:
    """Update tracker name, emoji, description or config."""
    async with async_session() as session:
        t = await session.scalar(
            select(Tracker).where(Tracker.id == uuid.UUID(tracker_id), Tracker.family_id == user.family_id)
        )
        if not t:
            raise HTTPException(status_code=404, detail="Tracker not found")
        if body.name is not None:
            t.name = body.name
        if body.emoji is not None:
            t.emoji = body.emoji
        if body.description is not None:
            t.description = body.description
        if body.config is not None:
            t.config = {**(t.config or {}), **body.config}
        await session.commit()
        await session.refresh(t)
    return _tracker_json(t)


@router.delete("/trackers/{tracker_id}")
async def delete_tracker(tracker_id: str, user: User = Depends(get_current_user)) -> dict:
    """Soft-delete a tracker (set is_active=False)."""
    async with async_session() as session:
        t = await session.scalar(
            select(Tracker).where(Tracker.id == uuid.UUID(tracker_id), Tracker.family_id == user.family_id)
        )
        if not t:
            raise HTTPException(status_code=404, detail="Tracker not found")
        t.is_active = False
        await session.commit()
    return {"ok": True}


@router.get("/trackers/{tracker_id}/entries")
async def list_tracker_entries(
    tracker_id: str,
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Return tracker entries for the last N days."""
    since = date.today().replace(day=date.today().day - min(days - 1, date.today().day - 1))
    from datetime import timedelta
    since = date.today() - timedelta(days=days - 1)

    async with async_session() as session:
        t = await session.scalar(
            select(Tracker).where(Tracker.id == uuid.UUID(tracker_id), Tracker.family_id == user.family_id)
        )
        if not t:
            raise HTTPException(status_code=404, detail="Tracker not found")

        entries = (await session.scalars(
            select(TrackerEntry)
            .where(TrackerEntry.tracker_id == t.id, TrackerEntry.date >= since)
            .order_by(TrackerEntry.date)
        )).all()
    return [_entry_json(e) for e in entries]


@router.post("/trackers/{tracker_id}/entries")
async def log_tracker_entry(
    tracker_id: str,
    body: TrackerEntryCreate,
    user: User = Depends(get_current_user),
) -> dict:
    """Log an entry for a tracker."""
    try:
        from datetime import date as date_cls
        entry_date = date_cls.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    async with async_session() as session:
        t = await session.scalar(
            select(Tracker).where(Tracker.id == uuid.UUID(tracker_id), Tracker.family_id == user.family_id)
        )
        if not t:
            raise HTTPException(status_code=404, detail="Tracker not found")

        entry = TrackerEntry(
            tracker_id=t.id,
            family_id=user.family_id,
            user_id=user.id,
            date=entry_date,
            value=body.value,
            data=body.data,
            note=body.note,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    return _entry_json(entry)


@router.delete("/trackers/{tracker_id}/entries/{entry_id}")
async def delete_tracker_entry(
    tracker_id: str,
    entry_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Delete a specific tracker entry."""
    async with async_session() as session:
        e = await session.scalar(
            select(TrackerEntry).where(
                TrackerEntry.id == uuid.UUID(entry_id),
                TrackerEntry.tracker_id == uuid.UUID(tracker_id),
                TrackerEntry.family_id == user.family_id,
            )
        )
        if not e:
            raise HTTPException(status_code=404, detail="Entry not found")
        await session.delete(e)
        await session.commit()
    return {"ok": True}
