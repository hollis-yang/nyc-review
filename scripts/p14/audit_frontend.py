#!/usr/bin/env python3
"""Static bilingual, Agent and map regression checks for P14."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REACT = ROOT / "nyc-review-web"


def flatten(value: dict, prefix: str = "") -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, path))
        else:
            result[path] = item
    return result


def main() -> int:
    locale_dir = REACT / "src/i18n/locales"
    english = flatten(json.loads((locale_dir / "en.json").read_text(encoding="utf-8")))
    chinese = flatten(json.loads((locale_dir / "zh-CN.json").read_text(encoding="utf-8")))
    missing_chinese = sorted(set(english) - set(chinese))
    missing_english = sorted(set(chinese) - set(english))

    categories = (
        "Food & Dining",
        "Cafes & Desserts",
        "Bars & Nightlife",
        "Entertainment & Attractions",
        "Fitness & Wellness",
        "Beauty & Personal Care",
    )
    category_failures = []
    for category in categories:
        key = f"shopTypes.{category}"
        if not english.get(key) or not chinese.get(key) or english.get(key) == chinese.get(key):
            category_failures.append(key)

    map_source = (REACT / "src/pages/Map/index.tsx").read_text(encoding="utf-8")
    agent_api_source = (REACT / "src/api/agent.ts").read_text(encoding="utf-8")
    ai_source = (REACT / "src/pages/AiWorkspace/index.tsx").read_text(encoding="utf-8")
    contract_checks = {
        "mapCancelsSupersededRequests": "new AbortController()" in map_source
        and "sequence !== requestSequence.current" in map_source,
        "mapKeepsFiveHundredMarkerBoundary": "MAX_POINTS = 500" in (
            ROOT / "src/main/java/com/nycreview/service/ShopMapService.java"
        ).read_text(encoding="utf-8"),
        "agentHttpClientHasNoDeadline": "timeout:" not in agent_api_source,
        "multiAgentOnly": "const MULTI_AGENTS" in ai_source
        and all(
            name in ai_source
            for name in ("Supervisor", "Discovery", "Evidence", "Itinerary", "Verifier")
        ),
        "verifierWarningsStayInternal": "issue.severity !== 'error'" in ai_source,
    }

    report = {
        "status": "ok",
        "localeKeys": len(english),
        "missingChineseKeys": missing_chinese,
        "missingEnglishKeys": missing_english,
        "categoryTranslationFailures": category_failures,
        "contracts": contract_checks,
    }
    if missing_chinese or missing_english or category_failures or not all(contract_checks.values()):
        report["status"] = "failed"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
