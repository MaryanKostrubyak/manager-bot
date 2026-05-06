from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Category, Transaction, TransactionType
from app.utils.categories import localize_category_name

settings = get_settings()


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def kpi_dashboard(self, user_id: int) -> dict[str, object]:
        total_records = await self.session.scalar(
            select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
        )
        avg_expense = await self.session.scalar(
            select(func.avg(Transaction.amount)).where(
                Transaction.user_id == user_id,
                Transaction.direction == TransactionType.EXPENSE,
            )
        )

        last_30_days = datetime.utcnow() - timedelta(days=30)
        stmt = select(Transaction.occurred_at, Transaction.amount).where(
            Transaction.user_id == user_id,
            Transaction.occurred_at >= last_30_days,
        )
        rows = (await self.session.execute(stmt)).all()
        heatmap = defaultdict(float)
        for occurred_at, amount in rows:
            if not occurred_at:
                continue
            key = f"{occurred_at.weekday()}-{occurred_at.hour}"
            heatmap[key] += float(amount or 0)

        return {
            "total_records": total_records or 0,
            "average_expense": float(avg_expense or 0),
            "heatmap": dict(heatmap),
        }

    async def export_csv(self, user_id: int, start: datetime, end: datetime) -> Path:
        stmt = (
            select(
                Transaction.id,
                Transaction.occurred_at,
                Transaction.amount,
                Transaction.currency,
                Transaction.direction,
                Transaction.description,
            )
            .where(Transaction.user_id == user_id)
            .where(Transaction.occurred_at >= start, Transaction.occurred_at <= end)
            .order_by(Transaction.occurred_at)
        )
        result = (await self.session.execute(stmt)).all()
        df = pd.DataFrame(
            result,
            columns=[
                "id",
                "occurred_at",
                "amount",
                "currency",
                "direction",
                "description",
            ],
        )
        file_name = f"transactions_{user_id}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
        path = settings.export_dir / file_name
        df.to_csv(path, index=False)
        return path


    async def category_chart(
        self, user_id: int, start: datetime, end: datetime, currency: str, chart_type: str = "category_bar"
    ) -> BytesIO | None:
        if chart_type == "trend_line":
            return await self._trend_chart(user_id, start, end, currency)

        stmt = (
            select(Category.name, Transaction.direction, func.sum(Transaction.amount).label("total"))
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(Transaction.user_id == user_id)
            .where(Transaction.occurred_at >= start, Transaction.occurred_at <= end)
            .group_by(Category.name, Transaction.direction)
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return None

        expenses = {}
        incomes = {}
        for name, direction, total in rows:
            label = localize_category_name(name or "Без категорії", default="Без категорії")
            if direction == TransactionType.EXPENSE:
                expenses[label] = float(total or 0)
            else:
                incomes[label] = float(total or 0)

        labels = list({*expenses.keys(), *incomes.keys()})
        expense_values = [expenses.get(label, 0.0) for label in labels]
        income_values = [incomes.get(label, 0.0) for label in labels]

        if chart_type == "category_pie":
            return self._category_pie_chart(expenses, incomes)

        return self._category_bar_chart(labels, expense_values, income_values, currency)

    def _category_bar_chart(
        self, labels: list[str], expense_values: list[float], income_values: list[float], currency: str
    ) -> BytesIO | None:
        if not labels:
            return None
        if not any(expense_values) and not any(income_values):
            return None

        buffer = BytesIO()
        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(labels))
        ax.bar(x, expense_values, width=0.4, label="Витрати", color="#ff7675")
        ax.bar([i + 0.4 for i in x], income_values, width=0.4, label="Доходи", color="#55efc4")
        ax.set_xticks([i + 0.2 for i in x])
        ax.set_xticklabels(labels, rotation=30, ha="right")
        ax.set_ylabel(currency)
        ax.set_title("Категорії за місяць")
        ax.legend()
        fig.tight_layout()
        fig.savefig(buffer, format="png", bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        return buffer

    def _category_pie_chart(self, expenses: dict[str, float], incomes: dict[str, float]) -> BytesIO | None:
        dataset = expenses if any(expenses.values()) else incomes
        if not dataset:
            return None

        total = sum(dataset.values())
        if total <= 0:
            return None

        labels = list(dataset.keys())
        values = [dataset[label] for label in labels]
        buffer = BytesIO()
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=140)
        ax.set_title("Структура витрат" if dataset is expenses else "Структура доходів")
        fig.tight_layout()
        fig.savefig(buffer, format="png", bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        return buffer

    async def _trend_chart(self, user_id: int, start: datetime, end: datetime, currency: str) -> BytesIO | None:
        stmt = (
            select(Transaction.occurred_at, Transaction.amount, Transaction.direction)
            .where(Transaction.user_id == user_id)
            .where(Transaction.occurred_at >= start, Transaction.occurred_at <= end)
            .order_by(Transaction.occurred_at)
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return None

        daily_totals: dict[date, dict[TransactionType, float]] = {}
        for occurred_at, amount, direction in rows:
            if not occurred_at:
                continue
            day = occurred_at.date()
            bucket = daily_totals.setdefault(
                day, {TransactionType.EXPENSE: 0.0, TransactionType.INCOME: 0.0}
            )
            bucket[direction] = bucket.get(direction, 0.0) + float(amount or 0)

        if not daily_totals:
            return None

        start_day = min(daily_totals)
        end_day = max(daily_totals)
        days = []
        current = start_day
        while current <= end_day:
            days.append(current)
            current += timedelta(days=1)

        expense_values = [daily_totals.get(day, {}).get(TransactionType.EXPENSE, 0.0) for day in days]
        income_values = [daily_totals.get(day, {}).get(TransactionType.INCOME, 0.0) for day in days]
        if not any(expense_values) and not any(income_values):
            return None

        labels = [day.strftime("%d.%m") for day in days]
        buffer = BytesIO()
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(labels, expense_values, label="Витрати", color="#ff7675", marker="o")
        ax.plot(labels, income_values, label="Доходи", color="#55efc4", marker="o")
        ax.set_ylabel(currency)
        ax.set_title("Щоденна динаміка")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(buffer, format="png", bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        return buffer
