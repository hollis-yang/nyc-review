from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

CATEGORY_NAMES = {
    1: "Food & Dining",
    2: "Cafes & Desserts",
    3: "Bars & Nightlife",
    4: "Entertainment & Attractions",
    5: "Fitness & Wellness",
    6: "Beauty & Personal Care",
}

TAG_LABELS = {
    "budget_friendly": "budget friendly",
    "date_night": "date night",
    "family_friendly": "family friendly",
    "good_for_groups": "good for groups",
    "halal": "halal",
    "late_night": "late night",
    "outdoor_seating": "outdoor seating",
    "pet_friendly": "pet friendly",
    "quiet": "quiet",
    "reservation_required": "reservation friendly",
    "vegan_options": "vegan options",
    "wheelchair_accessible": "wheelchair accessible",
}

CHINESE_TAG_LABELS = {
    "budget_friendly": "实惠",
    "date_night": "适合约会",
    "family_friendly": "适合亲子",
    "good_for_groups": "适合聚会",
    "halal": "清真",
    "late_night": "适合深夜",
    "outdoor_seating": "有户外座位",
    "pet_friendly": "宠物友好",
    "quiet": "安静",
    "vegan_options": "有纯素选择",
    "wheelchair_accessible": "无障碍",
}

CHINESE_CATEGORY_LABELS = {
    1: "餐厅",
    2: "咖啡甜品店",
    3: "酒吧",
    4: "景点",
    5: "健身场所",
    6: "美容护理店",
}


def build_suite(data_directory: Path) -> dict:
    shops = _read_json(data_directory / "shops.json")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))
    active_shops = [
        shop
        for shop in shops
        if shop.get("businessStatus", "OPERATIONAL") == "OPERATIONAL"
        and shop.get("externalId")
    ]
    neighborhood_sizes = Counter(
        (shop["typeId"], shop["neighborhood"]) for shop in active_shops
    )
    groups: dict[tuple[int, str, tuple[str, str]], list[dict]] = defaultdict(list)
    for shop in active_shops:
        tags = sorted(tag for tag in shop.get("tags") or [] if tag in TAG_LABELS)
        for pair in itertools.combinations(tags, 2):
            groups[(shop["typeId"], shop["neighborhood"], pair)].append(shop)

    cases: list[dict] = []
    for type_id, category in CATEGORY_NAMES.items():
        eligible = [
            (key, rows)
            for key, rows in groups.items()
            if key[0] == type_id
            and 2 <= len(rows) <= 10
            and neighborhood_sizes[(type_id, key[1])] <= 100
        ]
        english = _select_groups(eligible, 10)
        used = {key for key, _ in english}
        chinese_eligible = [
            item
            for item in eligible
            if item[0] not in used
            and set(item[0][2]) <= set(CHINESE_TAG_LABELS)
        ]
        chinese = _select_groups(chinese_eligible, 2)
        if len(english) != 10 or len(chinese) != 2:
            raise ValueError(f"Could not build 12 balanced cases for {category}.")
        for sequence, (key, rows) in enumerate(english, start=1):
            _, neighborhood, tags = key
            labels = [TAG_LABELS[tag] for tag in tags]
            cases.append(
                _case(
                    case_id=f"en-{type_id}-{sequence:02d}",
                    language="en",
                    query=(
                        f"Find a {labels[0]} and {labels[1]} {category.lower()} "
                        f"in {neighborhood}."
                    ),
                    category=category,
                    neighborhood=neighborhood,
                    tags=tags,
                    rows=rows,
                )
            )
        for sequence, (key, rows) in enumerate(chinese, start=1):
            _, neighborhood, tags = key
            labels = [CHINESE_TAG_LABELS[tag] for tag in tags]
            cases.append(
                _case(
                    case_id=f"zh-{type_id}-{sequence:02d}",
                    language="zh",
                    query=(
                        f"帮我找一家位于 {neighborhood}、{labels[0]}并且{labels[1]}的"
                        f"{CHINESE_CATEGORY_LABELS[type_id]}。"
                    ),
                    category=category,
                    neighborhood=neighborhood,
                    tags=tags,
                    rows=rows,
                )
            )

    canonical = json.dumps(cases, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "schemaVersion": 1,
        "suite": "p12-frozen-retrieval-v1",
        "retrievalVersion": "p12-rag-v1",
        "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"],
        "caseCount": len(cases),
        "caseSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "indexedDocuments": _expected_document_count(manifest),
        "cases": cases,
    }


def _select_groups(groups: list[tuple[tuple, list[dict]]], limit: int):
    selected = []
    used_neighborhoods: set[str] = set()
    used_tags: Counter[str] = Counter()
    remaining = list(groups)
    while remaining and len(selected) < limit:
        remaining.sort(
            key=lambda item: (
                item[0][1] in used_neighborhoods,
                sum(used_tags[tag] for tag in item[0][2]),
                abs(len(item[1]) - 5),
                item[0][1],
                item[0][2],
            )
        )
        chosen = remaining.pop(0)
        selected.append(chosen)
        used_neighborhoods.add(chosen[0][1])
        used_tags.update(chosen[0][2])
    return selected


def _case(
    *,
    case_id: str,
    language: str,
    query: str,
    category: str,
    neighborhood: str,
    tags: tuple[str, str],
    rows: list[dict],
) -> dict:
    return {
        "id": case_id,
        "language": language,
        "query": query,
        "constraints": {
            "query": query,
            "category": category,
            "neighborhood": neighborhood,
        },
        "semanticTags": list(tags),
        "expectedShopIds": sorted(shop["id"] for shop in rows),
        "expectedExternalIds": sorted(shop["externalId"] for shop in rows),
    }


def _read_json(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array.")
    return value


def _expected_document_count(manifest: dict) -> int:
    provenance = manifest.get("provenance") or {}
    return (
        int(provenance.get("realShops") or 0) * 3
        + int(provenance.get("syntheticReviewRoots") or 0)
        + int(provenance.get("syntheticBlogs") or 0)
        + int(provenance.get("syntheticBlogComments") or 0)
    )


def main() -> None:
    repository = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Build a deterministic P12 RAG eval suite.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p11-5-full",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "cases.json",
    )
    args = parser.parse_args()
    suite = build_suite(args.dataset.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(suite, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output.resolve()),
                "cases": suite["caseCount"],
                "dataVersion": suite["dataVersion"],
                "datasetSha256": suite["datasetSha256"],
                "caseSha256": suite["caseSha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
