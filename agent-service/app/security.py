from __future__ import annotations

import re
import time
from collections import defaultdict, deque


class PromptGuard:
    """Rejects explicit prompt-exfiltration/tool-bypass instructions at the API boundary."""

    _patterns = tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions?",
            r"reveal\s+(?:the\s+)?(?:system|developer)\s+prompt",
            r"show\s+(?:me\s+)?(?:your\s+)?hidden\s+instructions?",
            r"bypass\s+(?:the\s+)?(?:approval|confirmation|tool)\s+(?:policy|check|rules?)",
            r"execute\s+(?:the\s+)?(?:write|seckill)\s+tool\s+without\s+(?:approval|confirmation)",
        )
    )

    @classmethod
    def validate(cls, query: str) -> None:
        normalized = query.strip()
        if any(pattern.search(normalized) for pattern in cls._patterns):
            raise ValueError(
                "The request contains instructions that attempt to bypass Agent safety boundaries."
            )


class SlidingWindowRateLimiter:
    def __init__(self, requests: int, window_seconds: float = 60.0):
        self._requests = max(1, requests)
        self._window_seconds = max(1.0, window_seconds)
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self._windows[key]
        threshold = now - self._window_seconds
        while window and window[0] <= threshold:
            window.popleft()
        if len(window) >= self._requests:
            return False
        window.append(now)
        return True
