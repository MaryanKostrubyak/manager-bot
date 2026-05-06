from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any


class InvalidWebSessionToken(Exception):
    """Raised when a signed web session token is invalid or expired."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _sign(payload: bytes, secret: str) -> bytes:
    if not secret:
        raise ValueError("web session secret is not configured")
    return hmac.new(secret.encode(), payload, hashlib.sha256).digest()


def create_web_session_token(
    *,
    user_id: int,
    telegram_id: int,
    profile: dict[str, Any] | None,
    secret: str,
    lifetime_seconds: int,
) -> tuple[str, int]:
    if lifetime_seconds <= 0:
        raise ValueError("web session lifetime must be positive")
    issued_at = int(time.time())
    expires_at = issued_at + lifetime_seconds
    payload = {
        "uid": user_id,
        "tid": telegram_id,
        "exp": expires_at,
        "iat": issued_at,
        "profile": profile or {},
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = _sign(body, secret)
    token = f"{_b64encode(body)}.{_b64encode(signature)}"
    return token, expires_at


def verify_web_session_token(token: str, secret: str) -> dict[str, Any]:
    if not token:
        raise InvalidWebSessionToken("session token is empty")
    parts = token.split(".")
    if len(parts) != 2:
        raise InvalidWebSessionToken("session token structure is invalid")
    body_raw, signature_raw = parts
    try:
        body = _b64decode(body_raw)
        provided_signature = _b64decode(signature_raw)
    except (ValueError, binascii.Error) as exc:
        raise InvalidWebSessionToken("session token encoding error") from exc

    expected_signature = _sign(body, secret)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise InvalidWebSessionToken("session token signature mismatch")
    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError as exc:
        raise InvalidWebSessionToken("session token payload is malformed") from exc

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise InvalidWebSessionToken("session token expiration is missing")
    if expires_at < int(time.time()):
        raise InvalidWebSessionToken("session token expired")
    return payload
