from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

from qdrant_client import models

ALIASES = {
    "安静": "quiet",
    "清静": "quiet",
    "素食": "vegan_options",
    "纯素": "vegan_options",
    "无障碍": "wheelchair_accessible",
    "户外座位": "outdoor_seating",
    "户外": "outdoor_seating",
    "深夜": "late_night",
    "夜生活": "late_night",
    "适合聚会": "good_for_groups",
    "团体": "good_for_groups",
    "亲子": "family_friendly",
    "宠物友好": "pet_friendly",
    "实惠": "budget_friendly",
    "便宜": "budget_friendly",
    "约会": "date_night",
    "清真": "halal",
    "餐厅": "food dining",
    "美食": "food dining",
    "咖啡": "cafes desserts",
    "甜品": "cafes desserts",
    "酒吧": "bars nightlife",
    "景点": "entertainment attractions",
    "健身": "fitness wellness",
    "美容": "beauty personal care",
}

ENGLISH_ALIASES = {
    "calm": "quiet",
    "peaceful": "quiet",
    "plant based": "vegan_options",
    "plant-based": "vegan_options",
    "accessible": "wheelchair_accessible",
    "wheelchair": "wheelchair_accessible",
    "patio": "outdoor_seating",
    "outdoor seating": "outdoor_seating",
    "late night": "late_night",
    "groups": "good_for_groups",
    "group friendly": "good_for_groups",
    "family": "family_friendly",
    "dog friendly": "pet_friendly",
    "affordable": "budget_friendly",
    "cheap": "budget_friendly",
    "romantic": "date_night",
}

CANONICAL_TAGS = frozenset(
    {
        "budget_friendly",
        "date_night",
        "family_friendly",
        "good_for_groups",
        "halal",
        "late_night",
        "outdoor_seating",
        "pet_friendly",
        "quiet",
        "reservation_required",
        "vegan_options",
        "wheelchair_accessible",
    }
)

TAG_ALIASES = {
    **{
        tag.replace("_", " "): tag
        for tag in CANONICAL_TAGS
    },
    **{
        phrase: canonical
        for phrase, canonical in {**ALIASES, **ENGLISH_ALIASES}.items()
        if canonical in CANONICAL_TAGS
    },
}


def expand_query(text: str, canonical_terms: list[str] | None = None) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    expansions: list[str] = []
    for phrase, canonical in {**ALIASES, **ENGLISH_ALIASES}.items():
        if phrase in normalized:
            expansions.append(canonical)
    expansions.extend(term for term in canonical_terms or [] if term)
    return " ".join([text.strip(), *dict.fromkeys(expansions)]).strip()


def canonical_tags(text: str, explicit_tags: list[str] | None = None) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    discovered = [
        canonical
        for phrase, canonical in TAG_ALIASES.items()
        if phrase in normalized
    ]
    discovered.extend(tag for tag in explicit_tags or [] if tag in CANONICAL_TAGS)
    return sorted(set(discovered))


def lexical_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    words = re.findall(r"[a-z0-9]+(?:_[a-z0-9]+)*", normalized)
    word_bigrams = [
        f"{left}::{right}" for left, right in zip(words, words[1:], strict=False)
    ]
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk_tokens: list[str] = []
    for run in cjk_runs:
        cjk_tokens.extend(run)
        cjk_tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return [*words, *word_bigrams, *cjk_tokens]


def sparse_vector(text: str) -> models.SparseVector:
    counts = Counter(lexical_tokens(text))
    weighted: list[tuple[int, float]] = []
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % 2_147_483_647
        weighted.append((index, 1.0 + math.log(count)))
    weighted.sort(key=lambda item: item[0])
    return models.SparseVector(
        indices=[item[0] for item in weighted],
        values=[item[1] for item in weighted],
    )


def normalized_merchant_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = re.sub(r"\b(?:nyc|new york|manhattan|brooklyn|queens|bronx)\b", " ", normalized)
    return " ".join(re.findall(r"[a-z0-9]+", normalized))
