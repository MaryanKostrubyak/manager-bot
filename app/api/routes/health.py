from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok"}