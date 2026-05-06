from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qsl


class InvalidInitDataError(Exception):
    """Raised when Telegram WebApp init data fails validation."""


class InvalidTelegramLoginError(Exception):
    """Raised when Telegram Login Widget data fails validation."""


def parse_webapp_init_data(init_data: str, bot_token: str) -> dict[str, Any]:
    if not init_data:
        raise InvalidInitDataError("init data is empty")
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InvalidInitDataError("hash is missing")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if computed_hash != received_hash:
        raise InvalidInitDataError("init data hash mismatch")

    if "user" in data:
        try:
            data["user"] = json.loads(data["user"])
        except json.JSONDecodeError as exc:  # pragma: no cover - depends on user payload
            raise InvalidInitDataError("unable to parse user payload") from exc
    return data


def parse_telegram_login_data(login_data: str, bot_token: str) -> dict[str, Any]:
    if not login_data:
        raise InvalidTelegramLoginError("login data is empty")
    data = dict(parse_qsl(login_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InvalidTelegramLoginError("hash is missing")
    auth_date = data.get("auth_date")
    if not auth_date:
        raise InvalidTelegramLoginError("auth_date is missing")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if computed_hash != received_hash:
        raise InvalidTelegramLoginError("login data hash mismatch")

    for key in ("id", "auth_date"):
        if key in data:
            try:
                data[key] = int(data[key])
            except ValueError as exc:  # pragma: no cover - depends on payload
                raise InvalidTelegramLoginError(f"{key} must be an integer") from exc
    return data
