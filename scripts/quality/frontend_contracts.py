#!/usr/bin/env python3
"""Static bilingual, Agent and map frontend contract checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REACT = ROOT / "nyc-review-web"
LITERAL_TRANSLATION_CALL = re.compile(r"\b(?:t|tt)\(\s*(['\"`])([^'\"`\n]+)\1")
INTERPOLATION_PLACEHOLDER = re.compile(r"{{\s*([\w.-]+)")


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
    placeholder_mismatches = sorted(
        key
        for key in set(english) & set(chinese)
        if set(INTERPOLATION_PLACEHOLDER.findall(str(english[key])))
        != set(INTERPOLATION_PLACEHOLDER.findall(str(chinese[key])))
    )

    used_translation_keys: set[str] = set()
    for source_path in (REACT / "src").rglob("*"):
        if source_path.suffix not in {".ts", ".tsx"}:
            continue
        source = source_path.read_text(encoding="utf-8")
        for match in LITERAL_TRANSLATION_CALL.finditer(source):
            key = match.group(2)
            if "${" not in key:
                used_translation_keys.add(key)
    missing_used_english = sorted(used_translation_keys - set(english))
    missing_used_chinese = sorted(used_translation_keys - set(chinese))

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
        "literalTranslationKeysUsed": len(used_translation_keys),
        "missingChineseKeys": missing_chinese,
        "missingEnglishKeys": missing_english,
        "placeholderMismatches": placeholder_mismatches,
        "missingUsedChineseKeys": missing_used_chinese,
        "missingUsedEnglishKeys": missing_used_english,
        "categoryTranslationFailures": category_failures,
        "contracts": contract_checks,
    }
    if (
        missing_chinese
        or missing_english
        or missing_used_chinese
        or missing_used_english
        or placeholder_mismatches
        or category_failures
        or not all(contract_checks.values())
    ):
        report["status"] = "failed"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
