from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BudgetLimit, BudgetPeriod, Transaction, TransactionType
from app.schemas import BudgetLimitCreate, BudgetLimitRead, BudgetProgress
from app.utils.categories import localize_category_name

AlertCallback = Callable[[BudgetLimit, Decimal, Decimal], Awaitable[None]]


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_limits(self, user_id: int) -> list[BudgetLimit]:
        stmt = (
            select(BudgetLimit)
            .options(selectinload(BudgetLimit.category))
            .where(BudgetLimit.user_id == user_id, BudgetLimit.is_active.is_(True))
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def all_limits(self) -> list[BudgetLimit]:
        stmt = (
            select(BudgetLimit)
            .options(selectinload(BudgetLimit.user), selectinload(BudgetLimit.category))
            .where(BudgetLimit.is_active.is_(True))
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def create_limit(self, user_id: int, payload: BudgetLimitCreate) -> BudgetLimit:
        limit = BudgetLimit(
            user_id=user_id,
            category_id=payload.category_id,
            amount=payload.amount,
            period=payload.period,
            alert_threshold=payload.alert_threshold,
        )
        self.session.add(limit)
        await self.session.flush()
        await self.session.refresh(limit)
        return limit

    async def delete_limit(self, user_id: int, limit_id: int) -> bool:
        stmt = select(BudgetLimit).where(BudgetLimit.id == limit_id, BudgetLimit.user_id == user_id)
        limit = await self.session.scalar(stmt)
        if not limit:
            return False
        await self.session.delete(limit)
        return True

    async def limits_for_category(self, user_id: int, category_id: int) -> list[BudgetLimit]:
        stmt = (
            select(BudgetLimit)
            .options(selectinload(BudgetLimit.category))
            .where(BudgetLimit.user_id == user_id)
            .where(BudgetLimit.category_id == category_id)
            .where(BudgetLimit.is_active.is_(True))
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def progress(self, limit: BudgetLimit) -> BudgetProgress:
        start = _period_start(limit.period)
        spent = await self._spent(limit.user_id, limit.category_id, start)
        remaining = (limit.amount or Decimal("0")) - spent
        if remaining < Decimal("0"):
            remaining = Decimal("0")
        percent = float(spent / limit.amount * Decimal("100")) if limit.amount else 0.0
        payload = BudgetLimitRead(
            id=limit.id,
            category_id=limit.category_id,
            amount=limit.amount,
            period=limit.period,
            alert_threshold=limit.alert_threshold,
            is_active=limit.is_active,
            created_at=limit.created_at,
            category_name=localize_category_name(limit.category.name if limit.category else None),
        )
        return BudgetProgress(limit=payload, spent=spent, percent=percent, remaining=remaining)

    async def check_limits(self, limit: BudgetLimit, callback: AlertCallback) -> None:
        start = _period_start(limit.period)
        spent = await self._spent(limit.user_id, limit.category_id, start)
        if spent is None:
            spent = Decimal("0")
        if not limit.amount:
            return
        if spent / limit.amount >= Decimal(str(limit.alert_threshold)):
            await callback(limit, spent, limit.amount)

    async def check_limits_for_category(
        self, user_id: int, category_id: int, callback: AlertCallback
    ) -> None:
        limits = await self.limits_for_category(user_id, category_id)
        for limit in limits:
            await self.check_limits(limit, callback)

    async def _spent(self, user_id: int, category_id: int, start: datetime) -> Decimal:
        stmt = (
            select(func.sum(Transaction.amount))
            .where(Transaction.user_id == user_id)
            .where(Transaction.category_id == category_id)
            .where(Transaction.direction == TransactionType.EXPENSE)
            .where(Transaction.occurred_at >= start)
        )
        total = await self.session.scalar(stmt)
        return total or Decimal("0")


def _period_start(period: BudgetPeriod, reference: datetime | None = None) -> datetime:
    reference = reference or datetime.utcnow()
    if period == BudgetPeriod.DAILY:
        return datetime(reference.year, reference.month, reference.day)
    if period == BudgetPeriod.WEEKLY:
        start = reference - timedelta(days=reference.weekday())
        return datetime(start.year, start.month, start.day)
    if period == BudgetPeriod.MONTHLY:
        return datetime(reference.year, reference.month, 1)
    return reference
