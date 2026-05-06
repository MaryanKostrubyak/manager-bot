from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from telegram import Update
from telegram.ext import Application

from app.api.deps import get_settings_dep, get_telegram_app
from app.core.config import Settings

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    telegram_app: Application = Depends(get_telegram_app),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    if secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret")

    payload = await request.json()
    update = Update.de_json(payload, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "accepted"}


@router.get("/webhook/health")
async def webhook_health() -> dict[str, str]:
    return {"status": "listening"}