from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

_WEEKDAYS = {
    name.casefold(): day
    for day, name in enumerate(
        (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ),
        start=1,
    )
}
_NATURAL_VISIT_TIME = re.compile(
    r"^\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s+at\s+(.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocalVisitTime:
    day_of_week: int
    local_time: time


def parse_visit_time(
    value: str,
    *,
    timezone_name: str | None = None,
) -> LocalVisitTime | None:
    """Parse the public ISO contract and the deterministic weekday/time form."""

    if not isinstance(value, str) or not value.strip():
        return None
    natural = _NATURAL_VISIT_TIME.fullmatch(value)
    if natural is not None:
        parsed_time = _parse_clock(natural.group(2))
        if parsed_time is None:
            return None
        return LocalVisitTime(
            day_of_week=_WEEKDAYS[natural.group(1).casefold()],
            local_time=parsed_time,
        )

    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        timezone = ZoneInfo(timezone_name or "America/New_York")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone)
        else:
            moment = moment.astimezone(timezone)
    except (TypeError, ValueError, KeyError):
        return None
    return LocalVisitTime(
        day_of_week=moment.isoweekday(),
        local_time=moment.time().replace(tzinfo=None),
    )


def is_shop_open(candidate: Any, visit_time: str) -> bool:
    parsed = parse_visit_time(
        visit_time,
        timezone_name=_value(candidate, "timezone"),
    )
    if parsed is None:
        return False
    return is_open_at(
        _value(candidate, "business_hours", "businessHours") or (),
        day_of_week=parsed.day_of_week,
        local_time=parsed.local_time,
    )


def is_open_at(
    hours: Iterable[Any],
    *,
    day_of_week: int,
    local_time: str | time,
) -> bool:
    """Evaluate weekly hours, including the previous day's overnight window.

    Malformed or incomplete schedule rows fail closed instead of raising and
    aborting the whole discovery run.
    """

    if not 1 <= day_of_week <= 7:
        return False
    target = _parse_clock(local_time) if isinstance(local_time, str) else local_time
    if target is None:
        return False
    rows_by_day: dict[int, Any] = {}
    try:
        for item in hours:
            day = int(_value(item, "day_of_week", "dayOfWeek") or 0)
            if 1 <= day <= 7:
                rows_by_day.setdefault(day, item)
    except (TypeError, ValueError):
        return False

    today = rows_by_day.get(day_of_week)
    today_window = _schedule_window(today)
    if today_window is not None:
        opening, closing, overnight = today_window
        if overnight:
            if target >= opening:
                return True
        elif opening <= target < closing:
            return True

    previous_day = 7 if day_of_week == 1 else day_of_week - 1
    previous_window = _schedule_window(rows_by_day.get(previous_day))
    return bool(
        previous_window is not None
        and previous_window[2]
        and target < previous_window[1]
    )


def _schedule_window(item: Any) -> tuple[time, time, bool] | None:
    if item is None or bool(_value(item, "closed")):
        return None
    opening = _parse_clock(_value(item, "open_time", "openTime"))
    closing = _parse_clock(_value(item, "close_time", "closeTime"))
    if opening is None or closing is None:
        return None
    overnight = bool(_value(item, "closes_next_day", "closesNextDay")) or closing <= opening
    return opening, closing, overnight


def _parse_clock(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = " ".join(value.strip().upper().split())
    for parser in (
        time.fromisoformat,
        lambda raw: datetime.strptime(raw, "%I:%M %p").time(),
    ):
        try:
            return parser(normalized).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _value(item: Any, *names: str) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
        return None
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return None
