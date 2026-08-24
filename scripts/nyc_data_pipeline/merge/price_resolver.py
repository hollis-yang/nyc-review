from __future__ import annotations

from typing import Any


def price_level(value: Any) -> int | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and set(stripped) == {"$"}:
            return min(4, len(stripped))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1 <= parsed <= 4 else None


def price_text(value: Any, level: int | None) -> str | None:
    text = str(value or "").strip()
    if text and len(text) <= 32:
        return text
    return "$" * level if level else None
