from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models import BudgetPeriod
from app.schemas.base import Schema


class BudgetLimitCreate(Schema):
    category_id: int
    amount: Decimal
    period: BudgetPeriod
    alert_threshold: float = 0.9


class BudgetLimitRead(BudgetLimitCreate):
    id: int
    is_active: bool
    created_at: datetime | None = None
    category_name: str | None = None


class BudgetProgress(Schema):
    limit: BudgetLimitRead
    spent: Decimal
    percent: float
    remaining: Decimal
