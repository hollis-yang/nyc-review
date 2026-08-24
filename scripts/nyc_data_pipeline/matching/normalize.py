from __future__ import annotations

import math
import re
import unicodedata
from urllib.parse import urlparse

PUNCTUATION = re.compile(r"[^a-z0-9]+")
STREET_ALIASES = {
    "avenue": "ave", "street": "st", "road": "rd", "boulevard": "blvd",
    "place": "pl", "drive": "dr", "lane": "ln", "highway": "hwy",
}


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    tokens = PUNCTUATION.sub(" ", text.lower()).split()
    return " ".join(STREET_ALIASES.get(token, token) for token in tokens)


def normalize_phone(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_domain(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def postcode(value: object) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value or ""))
    return match.group(1) if match else ""


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    first = math.radians(lat1)
    second = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(first) * math.cos(second) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
