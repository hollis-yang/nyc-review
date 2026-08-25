from __future__ import annotations

from datetime import time
from typing import Any

DAY_INDEX = {"mo": 1, "tu": 2, "we": 3, "th": 4, "fr": 5, "sa": 6, "su": 7}


def normalize_hours(value: Any, shop_id: int) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        if value and all("dayOfWeek" in item and "closed" in item for item in value):
            return [{**item, "shopId": shop_id} for item in value]
        return _schema_hours(value, shop_id)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        value = "; ".join(value)
    if not isinstance(value, str) or not value.strip():
        return None
    result: dict[int, dict[str, Any]] = {}
    for segment in value.lower().split(";"):
        if " " not in segment.strip():
            continue
        days, interval = segment.strip().split(None, 1)
        if interval in {"off", "closed"}:
            for day in _days(days):
                result[day] = _closed(shop_id, day)
            continue
        if "," in interval or "-" not in interval:
            continue
        open_value, close_value = interval.split("-", 1)
        if not _valid_time(open_value) or not _valid_time(close_value):
            continue
        for day in _days(days):
            result[day] = {
                "shopId": shop_id, "dayOfWeek": day, "closed": False,
                "openTime": f"{open_value}:00", "closeTime": f"{close_value}:00",
                "closesNextDay": close_value <= open_value,
            }
    if not result:
        return None
    return [result.get(day, _closed(shop_id, day)) for day in range(1, 8)]


def _schema_hours(values: list[dict[str, Any]], shop_id: int) -> list[dict[str, Any]] | None:
    result: dict[int, dict[str, Any]] = {}
    for entry in values:
        opens = str(entry.get("opens") or "")[:5]
        closes = str(entry.get("closes") or "")[:5]
        if not _valid_time(opens) or not _valid_time(closes):
            continue
        days = entry.get("dayOfWeek")
        if not isinstance(days, list):
            days = [days]
        for raw_day in days:
            token = str(raw_day or "").rsplit("/", 1)[-1][:2].lower()
            day = DAY_INDEX.get(token)
            if day:
                result[day] = {
                    "shopId": shop_id, "dayOfWeek": day, "closed": False,
                    "openTime": f"{opens}:00", "closeTime": f"{closes}:00",
                    "closesNextDay": closes <= opens,
                }
    return [result.get(day, _closed(shop_id, day)) for day in range(1, 8)] if result else None


def _days(value: str) -> list[int]:
    result: list[int] = []
    for part in value.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            first, last = DAY_INDEX.get(start[:2]), DAY_INDEX.get(end[:2])
            if first and last:
                current = first
                while True:
                    result.append(current)
                    if current == last:
                        break
                    current = 1 if current == 7 else current + 1
        elif DAY_INDEX.get(part[:2]):
            result.append(DAY_INDEX[part[:2]])
    return sorted(set(result))


def _valid_time(value: str) -> bool:
    try:
        time.fromisoformat(value)
        return len(value) == 5
    except ValueError:
        return False


def _closed(shop_id: int, day: int) -> dict[str, Any]:
    return {"shopId": shop_id, "dayOfWeek": day, "closed": True, "openTime": None, "closeTime": None, "closesNextDay": False}
