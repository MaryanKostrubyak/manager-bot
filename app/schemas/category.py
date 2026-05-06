from __future__ import annotations

from datetime import datetime

from app.models import CategoryType
from app.schemas.base import Schema


class CategoryCreate(Schema):
    name: str
    type: CategoryType = CategoryType.EXPENSE
    emoji: str | None = None


class CategoryRead(CategoryCreate):
    id: int
    user_id: int | None = None
    is_default: bool = False
    created_at: datetime | None = None