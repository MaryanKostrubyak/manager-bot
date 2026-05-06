from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_admin
from app.models import User
from app.schemas import AnalyticsSummary
from app.services.reports import ReportService
from app.services.transactions import TransactionService

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _get_user(session: AsyncSession, telegram_id: int) -> User:
    result = await session.scalars(select(User).where(User.telegram_id == telegram_id))
    user = result.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/summary/{telegram_id}", response_model=AnalyticsSummary)
async def monthly_summary(
    telegram_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    user = await _get_user(session, telegram_id)
    service = TransactionService(session)
    return await service.monthly_summary(user)


@router.get("/kpi/{telegram_id}")
async def kpi_dashboard(
    telegram_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_admin),
):
    user = await _get_user(session, telegram_id)
    service = ReportService(session)
    return await service.kpi_dashboard(user.id)


@router.get("/export/{telegram_id}")
async def export_csv(
    telegram_id: int,
    days: int = Query(30, ge=1, le=180),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_admin),
):
    user = await _get_user(session, telegram_id)
    service = ReportService(session)
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    path = await service.export_csv(user.id, start, end)
    return FileResponse(path, filename=path.name)