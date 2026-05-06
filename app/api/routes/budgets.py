from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models import User
from app.schemas import BudgetLimitCreate, BudgetLimitRead
from app.services.budgets import BudgetService

router = APIRouter(prefix="/budgets", tags=["budgets"])


async def _user(session: AsyncSession, telegram_id: int) -> User:
    result = await session.scalars(select(User).where(User.telegram_id == telegram_id))
    user = result.first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/{telegram_id}", response_model=list[BudgetLimitRead])
async def list_limits(telegram_id: int, session: AsyncSession = Depends(get_db_session)):
    user = await _user(session, telegram_id)
    service = BudgetService(session)
    limits = await service.list_limits(user.id)
    return [BudgetLimitRead.model_validate(limit) for limit in limits]


@router.post("/{telegram_id}", response_model=BudgetLimitRead)
async def create_limit(
    telegram_id: int,
    payload: BudgetLimitCreate,
    session: AsyncSession = Depends(get_db_session),
):
    user = await _user(session, telegram_id)
    service = BudgetService(session)
    limit = await service.create_limit(user.id, payload)
    await session.commit()
    return BudgetLimitRead.model_validate(limit)
