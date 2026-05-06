from __future__ import annotations

import sys

import sentry_sdk
from loguru import logger

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure application and Sentry logging."""

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        backtrace=settings.environment == "development",
        diagnose=settings.environment == "development",
        enqueue=True,
    )

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.telemetry_sample_rate,
            environment=settings.environment,
        )