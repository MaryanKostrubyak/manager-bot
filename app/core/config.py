from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_name: str = "Finance Assistant Bot"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./app.db"
    telemetry_sample_rate: float = 0.25

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    webhook_base_url: str | None = "http://localhost:8000"
    ngrok_api_url: str | None = None
    ngrok_tunnel_name: str | None = None

    default_currency: str = "UAH"
    supported_currencies: list[str] = Field(default_factory=lambda: ["UAH", "USD", "EUR"])
    default_language: str = "uk"
    supported_languages: list[str] = Field(default_factory=lambda: ["uk", "en"])
    default_theme: str = "dark"
    supported_themes: list[str] = Field(default_factory=lambda: ["dark", "light"])

    redis_url: str = "redis://localhost:6379/0"
    scheduler_tz: str = "Europe/Kyiv"

    sentry_dsn: str | None = None
    log_level: str = "INFO"

    export_dir: Path = Path("exports")
    admin_api_key: str = "change-me"

    report_timezone: str = "Europe/Kyiv"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    web_app_url: str | None = None
    web_session_secret: str = ""
    web_session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    return settings
