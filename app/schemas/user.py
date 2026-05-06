from __future__ import annotations

from datetime import datetime

from app.schemas.base import Schema


class UserCreate(Schema):
    telegram_id: int
    username: str | None = None
    currency: str | None = None
    language: str | None = None
    theme: str | None = None


class UserRead(Schema):
    id: int
    telegram_id: int
    username: str | None
    currency: str
    language: str
    theme: str
    onboarding_completed: bool
    created_at: datetime | None = None
