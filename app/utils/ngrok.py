from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from pathlib import Path

from app.core.config import Settings


async def fetch_ngrok_public_url(settings: Settings) -> str | None:
    """Query the ngrok API for the latest https public URL."""

    # First try shared file written by ngrok container (mounted volume).
    shared_file = Path("/home/ngrok/share/public_url")
    if shared_file.exists():
        text = shared_file.read_text().strip()
        if text.startswith("https://"):
            logger.info("Resolved ngrok public URL from shared file: {}", text)
            return text

    if not settings.ngrok_api_url:
        return None

    try:
        async with httpx.AsyncClient(base_url=settings.ngrok_api_url, timeout=5.0) as client:
            response = await client.get("/api/tunnels")
            response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failure logging
        logger.warning("Ngrok API unavailable: {}", exc)
        return None

    payload: dict[str, Any] = response.json()
    tunnels = payload.get("tunnels", [])
    target_name = settings.ngrok_tunnel_name

    for tunnel in tunnels:
        name = tunnel.get("name")
        if target_name and name != target_name:
            continue
        public_url = tunnel.get("public_url", "")
        if public_url.startswith("https://"):
            logger.info("Resolved ngrok public URL: {}", public_url)
            return public_url
    logger.warning("No https ngrok tunnel detected (target={})", target_name)
    return None
