from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models import TransactionType
from app.schemas.base import Schema


class TransactionCreate(Schema):
    amount: Decimal
    currency: str
    direction: TransactionType
    category_id: int | None = None
    wallet_id: int | None = None
    description: str | None = None
    tags: list[str] | None = None
    occurred_at: datetime | None = None


class TransactionRead(TransactionCreate):
    id: int
    user_id: int
    created_at: datetime | None = None