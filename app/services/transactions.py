from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, Transaction, TransactionType, User, Wallet
from app.schemas import AnalyticsSummary, CategoryBreakdown, TransactionCreate
from app.utils.categories import localize_category_name


class TransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_transaction(self, user: User, payload: TransactionCreate) -> Transaction:
        wallet_id = payload.wallet_id or await self._default_wallet_id(user)
        occurred_at = payload.occurred_at or datetime.utcnow()

        transaction = Transaction(
            user_id=user.id,
            wallet_id=wallet_id,
            category_id=payload.category_id,
            amount=payload.amount,
            currency=payload.currency or user.currency,
            direction=payload.direction,
            description=payload.description,
            tags=payload.tags or [],
            occurred_at=occurred_at,
        )
        self.session.add(transaction)
        await self.session.flush()
        await self.session.refresh(transaction)
        return transaction

    async def get_recent_transactions(
        self,
        user: User,
        limit: int = 10,
        month: date | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        source: str | None = None,
        offset: int = 0,
        q: str | None = None,
        direction: TransactionType | None = None,
        category_id: int | None = None,
        category_ids: list[int] | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        must_only: bool | None = None,
    ) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.user_id == user.id)
            .outerjoin(Category, Category.id == Transaction.category_id)
        )
        if direction:
            stmt = stmt.where(Transaction.direction == direction)
        if category_id is not None:
            stmt = stmt.where(Transaction.category_id == category_id)
        if category_ids:
            clean_ids = sorted({item for item in category_ids if item})
            if clean_ids:
                stmt = stmt.where(Transaction.category_id.in_(clean_ids))
        if amount_min is not None:
            stmt = stmt.where(Transaction.amount >= amount_min)
        if amount_max is not None:
            stmt = stmt.where(Transaction.amount <= amount_max)
        if must_only is True:
            stmt = stmt.where(Transaction.tags.contains(["must"]))
        elif must_only is False:
            stmt = stmt.where((Transaction.tags.is_(None)) | (~Transaction.tags.contains(["must"])))
        if source == "statement":
            stmt = stmt.where(Transaction.tags.contains(["statement_import"]))
        elif source == "manual":
            stmt = stmt.where((Transaction.tags.is_(None)) | (~Transaction.tags.contains(["statement_import"])))
        if q:
            normalized = q.strip()
            if normalized:
                pattern = f"%{normalized.lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(func.coalesce(Transaction.description, "")).like(pattern),
                        func.lower(func.coalesce(Category.name, "")).like(pattern),
                        cast(Transaction.amount, String).like(f"%{normalized}%"),
                    )
                )
        if start and end:
            stmt = stmt.where(Transaction.occurred_at >= start).where(Transaction.occurred_at < end)
        elif month:
            tz = ZoneInfo(user.timezone or "UTC")
            start_local, end_local = _month_bounds(month, tz)
            start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
            stmt = stmt.where(Transaction.occurred_at >= start_utc).where(Transaction.occurred_at < end_utc)
        stmt = stmt.order_by(Transaction.occurred_at.desc()).offset(offset).limit(limit)
        result = await self.session.scalars(stmt)
        return list(result)

    async def monthly_summary(
        self,
        user: User,
        target_month: date | None = None,
        source: str | None = None,
    ) -> AnalyticsSummary:
        tz = ZoneInfo(user.timezone or "UTC")
        reference = target_month or datetime.now(tz).date()
        start_local, end_local = _month_bounds(reference, tz)
        return await self.summary_for_period(user, start_local, end_local, source=source)

    async def available_months(self, user: User) -> list[str]:
        """Return list of months (YYYY-MM) where user has transactions, newest first."""
        stmt = select(
            func.min(Transaction.occurred_at),
            func.max(Transaction.occurred_at),
        ).where(Transaction.user_id == user.id)
        min_max = await self.session.execute(stmt)
        min_date, max_date = min_max.one()
        if not min_date or not max_date:
            return []
        start = date(min_date.year, min_date.month, 1)
        end = date(max_date.year, max_date.month, 1)
        months: list[str] = []
        current = end
        while current >= start:
            months.append(f"{current.year:04d}-{current.month:02d}")
            if current.month == 1:
                current = date(current.year - 1, 12, 1)
            else:
                current = date(current.year, current.month - 1, 1)
        return months

    async def all_time_summary(self, user: User) -> AnalyticsSummary:
        """Aggregate totals for all time."""
        stmt = (
            select(Category.name, Transaction.direction, func.sum(Transaction.amount).label("total"))
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(Transaction.user_id == user.id)
            .group_by(Category.name, Transaction.direction)
        )
        rows = (await self.session.execute(stmt)).all()
        totals: dict[TransactionType, Decimal] = {
            TransactionType.EXPENSE: Decimal("0"),
            TransactionType.INCOME: Decimal("0"),
        }
        breakdown: list[CategoryBreakdown] = []
        for category, direction, total in rows:
            total = total or Decimal("0")
            totals[direction] += total
            breakdown.append(
                CategoryBreakdown(
                    category=localize_category_name(category or "Без категорії", default="Без категорії"),
                    total=total,
                    direction=direction.value,
                )
            )
        net = totals[TransactionType.INCOME] - totals[TransactionType.EXPENSE]
        return AnalyticsSummary(
            total_income=totals[TransactionType.INCOME],
            total_expense=totals[TransactionType.EXPENSE],
            net=net,
            top_categories=sorted(breakdown, key=lambda x: x.total, reverse=True)[:5],
            currency=user.currency,
        )

    async def summary_for_period(
        self,
        user: User,
        start_local: datetime,
        end_local: datetime,
        source: str | None = None,
    ) -> AnalyticsSummary:
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        stmt = self._totals_query(user.id, start_utc, end_utc, source=source)
        rows = (await self.session.execute(stmt)).all()

        totals: dict[TransactionType, Decimal] = {
            TransactionType.EXPENSE: Decimal("0"),
            TransactionType.INCOME: Decimal("0"),
        }
        breakdown: list[CategoryBreakdown] = []
        for category, direction, total in rows:
            total = total or Decimal("0")
            totals[direction] += total
            breakdown.append(
                CategoryBreakdown(
                    category=localize_category_name(category or "Без категорії", default="Без категорії"),
                    total=total,
                    direction=direction.value,
                )
            )

        net = totals[TransactionType.INCOME] - totals[TransactionType.EXPENSE]
        return AnalyticsSummary(
            total_income=totals[TransactionType.INCOME],
            total_expense=totals[TransactionType.EXPENSE],
            net=net,
            top_categories=sorted(breakdown, key=lambda x: x.total, reverse=True)[:5],
            currency=user.currency,
        )

    def _totals_query(self, user_id: int, start: datetime, end: datetime, source: str | None = None) -> Select:
        stmt = (
            select(Category.name, Transaction.direction, func.sum(Transaction.amount).label("total"))
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(Transaction.user_id == user_id)
            .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
            .group_by(Category.name, Transaction.direction)
        )
        if source == "statement":
            stmt = stmt.where(Transaction.tags.contains(["statement_import"]))
        elif source == "manual":
            stmt = stmt.where((Transaction.tags.is_(None)) | (~Transaction.tags.contains(["statement_import"])))
        return stmt

    async def transactions_between(self, user: User, start: datetime, end: datetime) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.user_id == user.id)
            .where(Transaction.occurred_at >= start)
            .where(Transaction.occurred_at < end)
            .order_by(Transaction.occurred_at)
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def _default_wallet_id(self, user: User) -> int:
        stmt = select(Wallet.id).where(Wallet.user_id == user.id).order_by(Wallet.is_default.desc())
        wallet_id = await self.session.scalar(stmt)
        if not wallet_id:
            wallet = Wallet(user_id=user.id, name="Гаманець", currency=user.currency, is_default=True)
            self.session.add(wallet)
            await self.session.flush()
            return wallet.id
        return wallet_id

    async def get_transaction(self, user: User, transaction_id: int) -> Transaction | None:
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.id == transaction_id, Transaction.user_id == user.id)
        )
        return await self.session.scalar(stmt)

    async def delete_transaction(self, user: User, transaction_id: int) -> bool:
        transaction = await self.get_transaction(user, transaction_id)
        if not transaction:
            return False
        await self.session.delete(transaction)
        return True


def _month_bounds(target: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, 1, tzinfo=tz)
    if target.month == 12:
        end = datetime(target.year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(target.year, target.month + 1, 1, tzinfo=tz)
    return start, end
