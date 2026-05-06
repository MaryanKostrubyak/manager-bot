from __future__ import annotations

MERCHANT_ALIASES = {
    "atb": "???",
    "atb-market": "???",
    "silpo": "??????",
    "silpo-market": "??????",
    "novus": "NOVUS",
    "fozzy": "??????",
    "wolt": "Wolt",
    "glovo": "Glovo",
    "uber": "Uber",
    "uber*": "Uber",
    "bolt": "Bolt",
    "taxi": "Taxi",
    "spotify": "Spotify",
    "netflix": "Netflix",
    "apple.com": "Apple",
    "google": "Google",
}


def canonicalize_merchant(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() or ch in ".*" else " " for ch in raw)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    for alias, canonical in MERCHANT_ALIASES.items():
        if alias in cleaned:
            return canonical
    return cleaned[:40]
