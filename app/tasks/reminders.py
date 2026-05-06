from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import BudgetLimit, Transaction, TransactionType, User
from app.services.budgets import BudgetService
from app.utils.categories import localize_category_name
from app.utils.subscriptions import next_month_same_day, subscription_merchant_key


class ReminderManager:
    def __init__(self, scheduler: AsyncIOScheduler, telegram_app) -> None:
        self.scheduler = scheduler
        self.telegram_app = telegram_app
        self._subscription_notified: dict[str, datetime.date] = {}

    def start(self) -> None:
        if not self.scheduler.get_job("budget-check"):
            self.scheduler.add_job(self._budget_job, "interval", minutes=30, id="budget-check")
        if not self.scheduler.get_job("subscription-check"):
            self.scheduler.add_job(self._subscription_job, "interval", hours=12, id="subscription-check")
        if not self.scheduler.running:
            self.scheduler.start()

    async def _budget_job(self) -> None:
        async with AsyncSessionLocal() as session:
            service = BudgetService(session)
            for limit in await service.all_limits():
                await service.check_limits(limit, self._send_budget_alert)

    async def _send_budget_alert(self, limit: BudgetLimit, spent, total) -> None:
        if not limit.user:
            return
        category = localize_category_name(limit.category.name if limit.category else None, default="—")
        text = (
            "⚠️ Ліміт майже вичерпано!\n"
            f"Категорія: {category}\n"
            f"Витрачено {float(spent):.2f}/{float(total):.2f} ({limit.period.value})"
        )
        try:
            await self.telegram_app.bot.send_message(chat_id=limit.user.telegram_id, text=text)
        except Exception as exc:  # pragma: no cover - notification errors are logged
            logger.exception("Failed to send budget alert: {}", exc)

    async def _subscription_job(self) -> None:
        lookback_days = 90
        reminder_window_days = 3
        async with AsyncSessionLocal() as session:
            stmt = (
                select(
                    Transaction.user_id,
                    Transaction.description,
                    Transaction.amount,
                    Transaction.currency,
                    Transaction.occurred_at,
                    User.telegram_id,
                    User.timezone,
                )
                .join(User, User.id == Transaction.user_id)
                .where(Transaction.direction == TransactionType.EXPENSE)
                .where(Transaction.tags.contains(["subscription"]))
            )
            rows = (await session.execute(stmt)).all()

        grouped: dict[tuple[int, str], dict[str, object]] = {}
        for user_id, description, amount, currency, occurred_at, telegram_id, tz_name in rows:
            if not occurred_at or not telegram_id:
                continue
            tz = ZoneInfo(tz_name or "UTC")
            local_date = occurred_at.replace(tzinfo=timezone.utc).astimezone(tz).date()
            if (datetime.now(tz).date() - local_date).days > lookback_days:
                continue
            merchant_key = subscription_merchant_key(description)
            if not merchant_key:
                continue
            key = (user_id, merchant_key)
            current = grouped.get(key)
            if not current or (current["occurred_at"] and occurred_at > current["occurred_at"]):
                grouped[key] = {
                    "merchant": merchant_key,
                    "amount": float(amount or 0.0),
                    "currency": currency or "UAH",
                    "occurred_at": occurred_at,
                    "telegram_id": telegram_id,
                    "timezone": tz_name or "UTC",
                }

        for (user_id, merchant_key), info in grouped.items():
            tz = ZoneInfo(info["timezone"])
            last_local = info["occurred_at"].replace(tzinfo=timezone.utc).astimezone(tz).date()
            today = datetime.now(tz).date()
            next_due = next_month_same_day(last_local)
            days_until = (next_due - today).days
            if days_until < 0 or days_until > reminder_window_days:
                continue
            notify_key = f"{user_id}:{merchant_key}"
            if self._subscription_notified.get(notify_key) == next_due:
                continue
            text = (
                "🔔 Нагадування про підписку\n"
                f"Сервіс: {merchant_key}\n"
                f"Сума: {info['amount']:.2f} {info['currency']}\n"
                f"Очікувана дата: {next_due.strftime('%d.%m.%Y')}"
            )
            try:
                await self.telegram_app.bot.send_message(chat_id=info["telegram_id"], text=text)
                self._subscription_notified[notify_key] = next_due
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to send subscription reminder: {}", exc)
