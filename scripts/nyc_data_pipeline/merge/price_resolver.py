from __future__ import annotations

import re
from typing import Any


def price_level(value: Any) -> int | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and set(stripped) == {"$"}:
            return min(4, len(stripped))
        # Convert an official USD range into the platform's four coarse price
        # bands. This affects presentation only; the original range text stays
        # available in ``priceRangeText``.
        amounts = [float(item) for item in re.findall(r"(?<![A-Za-z])\$?\s*(\d+(?:\.\d+)?)", stripped)]
        if amounts:
            representative = sum(amounts[:2]) / min(2, len(amounts))
            if representative < 20:
                return 1
            if representative < 40:
                return 2
            if representative < 75:
                return 3
            return 4
        dollar_groups = re.findall(r"\$+", stripped)
        if dollar_groups:
            average = sum(map(len, dollar_groups)) / len(dollar_groups)
            return min(4, max(1, int(average + 0.5)))
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
