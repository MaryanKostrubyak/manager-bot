from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from telegram import BotCommand
from telegram.error import InvalidToken
from telegram.ext import Application

from app.api.routes import analytics, budgets, health, telegram, webapp
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.tasks.reminders import ReminderManager
from app.telegram.bot import TelegramBot
from app.utils.ngrok import fetch_ngrok_public_url

settings = get_settings()
configure_logging(settings)
scheduler = AsyncIOScheduler(timezone=settings.scheduler_tz)


def _build_telegram_runtime() -> tuple[TelegramBot | None, Application | None, ReminderManager | None]:
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot disabled: TELEGRAM_BOT_TOKEN is empty.")
        return None, None, None

    try:
        telegram_bot = TelegramBot(settings)
        telegram_application = telegram_bot.build_application()
    except InvalidToken as exc:
        logger.error("Telegram bot disabled: {}", exc)
        return None, None, None

    reminder_manager = ReminderManager(scheduler, telegram_application)
    return telegram_bot, telegram_application, reminder_manager


async def _resolve_webhook_base_url() -> str | None:
    if settings.webhook_base_url:
        return settings.webhook_base_url
    # Try a few times to wait for ngrok tunnel to appear.
    attempts = 5
    delay = 2
    for idx in range(attempts):
        url = await fetch_ngrok_public_url(settings)
        if url:
            return url
        if idx < attempts - 1:
            await asyncio.sleep(delay)
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.tg_application = None
    app.state.webhook_base_url = None
    reminder_started = False
    bot_started = False
    polling_task: asyncio.Task | None = None

    telegram_bot, telegram_application, reminder_manager = _build_telegram_runtime()

    if not telegram_bot or not telegram_application or not reminder_manager:
        yield
        return

    try:
        await telegram_application.initialize()
        await telegram_application.start()
        bot_started = True
        await telegram_application.bot.set_my_commands(
            [
                BotCommand("start", "Почати роботу"),
                BotCommand("history", "Останні операції"),
                BotCommand("settings", "Налаштування"),
                BotCommand("timezone", "Часовий пояс"),
                BotCommand("web", "Мініапка"),
            ]
        )

        resolved_base = await _resolve_webhook_base_url()
        app.state.webhook_base_url = resolved_base

        configured_web = settings.web_app_url if settings.web_app_url else None
        web_app_base = configured_web or resolved_base or "http://localhost:8000"
        cache_bust = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        web_app_url = f"{web_app_base.rstrip('/')}/webapp/?v={cache_bust}"
        telegram_bot.update_web_app_url(web_app_url)

        if resolved_base and resolved_base.startswith("https://") and settings.telegram_webhook_secret:
            await telegram_application.bot.set_webhook(
                f"{resolved_base}/telegram/webhook/{settings.telegram_webhook_secret}",
                secret_token=settings.telegram_webhook_secret,
                allowed_updates=["message", "callback_query"],
            )
        else:
            logger.warning(
                "Skipping webhook registration: base URL or secret missing (base={})",
                resolved_base,
            )
            # Fallback to long polling when webhook is unavailable.
            async def _poll_updates():
                offset = None
                webhook_cleared = False
                try:
                    await telegram_application.bot.delete_webhook(drop_pending_updates=True)
                    webhook_cleared = True
                except Exception as exc:  # pragma: no cover - network related
                    logger.warning("Failed to delete webhook before polling: {}", exc)
                while True:
                    try:
                        updates = await telegram_application.bot.get_updates(offset=offset, timeout=30)
                        for update in updates:
                            offset = update.update_id + 1
                            await telegram_application.process_update(update)
                    except asyncio.CancelledError:
                        break
                    except Exception as exc:  # pragma: no cover - network related
                        message = str(exc)
                        if "webhook is active" in message:
                            if not webhook_cleared:
                                try:
                                    await telegram_application.bot.delete_webhook(drop_pending_updates=True)
                                    webhook_cleared = True
                                    continue
                                except Exception as delete_exc:  # pragma: no cover
                                    logger.warning("Failed to delete webhook after conflict: {}", delete_exc)
                        logger.warning("Polling failed: {}", exc)
                        await asyncio.sleep(2)

            polling_task = asyncio.create_task(_poll_updates())

        reminder_manager.start()
        reminder_started = True
        app.state.tg_application = telegram_application

        yield
    finally:
        if bot_started:
            if polling_task:
                polling_task.cancel()
                with suppress(Exception):
                    await asyncio.gather(polling_task, return_exceptions=True)
            await telegram_application.stop()
        if reminder_started and scheduler.running:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.project_name, lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.include_router(health.router)
    app.include_router(telegram.router)
    app.include_router(analytics.router, prefix=settings.api_v1_prefix)
    app.include_router(budgets.router, prefix=settings.api_v1_prefix)
    app.include_router(webapp.router, prefix=f"{settings.api_v1_prefix}")
    app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")
    return app


app = create_app()
