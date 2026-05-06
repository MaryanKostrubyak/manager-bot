from __future__ import annotations


def repair_text(value: str | None) -> str:
    if value is None:
        return ""
    if not value:
        return value
    for encoding in ("cp1251", "latin1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if repaired and any("\u0400" <= ch <= "\u04FF" or ch in "·–—«»" for ch in repaired):
            return repaired
    return value
