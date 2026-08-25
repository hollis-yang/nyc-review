from __future__ import annotations

from typing import Any


def rating_tenths(value: Any) -> int | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed * 10) if 0 <= parsed <= 5 else None


def count(value: Any) -> int | None:
    if isinstance(value, str):
        text = value.strip().lower().replace(",", "")
        multiplier = 1
        if text.endswith("k"):
            multiplier, text = 1_000, text[:-1]
        elif text.endswith("m"):
            multiplier, text = 1_000_000, text[:-1]
        try:
            parsed_float = float(text) * multiplier
        except ValueError:
            return None
        return round(parsed_float) if parsed_float >= 0 else None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
