from __future__ import annotations

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import Application

from app.core.config import Settings, get_settings
from app.db.session import get_session


async def get_db_session() -> AsyncSession:
    async for session in get_session():
        yield session


def get_settings_dep() -> Settings:
    return get_settings()


def get_telegram_app(request: Request) -> Application:
    app = getattr(request.app.state, "tg_application", None)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not initialized. Configure TELEGRAM_BOT_TOKEN.",
        )
    return app


def require_admin(api_key: str = Header(..., alias="x-api-key")) -> None:
    settings = get_settings()
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
