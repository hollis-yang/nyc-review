from __future__ import annotations

from typing import Any


def rating_tenths(value: Any) -> int | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed * 10) if 0 <= parsed <= 5 else None


def count(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
