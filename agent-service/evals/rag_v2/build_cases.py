from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.rag.lexical import canonical_tags
from evals.rag_v2.contract import fixture_contract_sha256, suite_contract_sha256

CATEGORY_NAMES = {
    1: "Food & Dining",
    2: "Cafes & Desserts",
    3: "Bars & Nightlife",
    4: "Entertainment & Attractions",
    5: "Fitness & Wellness",
    6: "Beauty & Personal Care",
}

CHINESE_CATEGORY_NAMES = {
    1: "餐厅",
    2: "咖啡甜品店",
    3: "酒吧",
    4: "休闲景点",
    5: "健身场所",
    6: "美容护理店",
}

TAG_PHRASES = {
    "budget_friendly": {
        "en": ["easy on the wallet", "won't wreck the budget", "reasonably priced"],
        "zh": ["花费别太高", "价格亲民", "不太伤钱包"],
        "mixed": ["预算友好", "budget-friendly", "不会太贵"],
    },
    "date_night": {
        "en": [
            "right for an anniversary",
            "somewhere two people can linger",
            "romantic without being formal",
        ],
        "zh": ["适合两个人慢慢约会", "有纪念日晚餐氛围", "适合情侣相处"],
        "mixed": ["适合 date night", "有 romantic vibe", "适合两个人约会"],
    },
    "family_friendly": {
        "en": ["comfortable with kids", "welcoming to the whole family", "easy for parents and children"],
        "zh": ["带孩子也轻松", "全家去都合适", "对亲子比较友好"],
        "mixed": ["适合 family outing", "kids-friendly", "全家都能去"],
    },
    "good_for_groups": {
        "en": ["able to handle a small crowd", "suited to a group meetup", "room for several friends"],
        "zh": ["一群朋友去也方便", "适合多人碰面", "能坐下好几个人"],
        "mixed": ["适合 group meetup", "多人聚会 friendly", "朋友多也能坐"],
    },
    "halal": {
        "en": ["with halal choices", "serving food that follows halal requirements", "halal-suitable"],
        "zh": ["能满足清真饮食", "提供清真选择", "符合清真要求"],
        "mixed": ["有 halal 选择", "符合 halal 要求", "清真-friendly"],
    },
    "late_night": {
        "en": [
            "still useful after a late show",
            "open when the evening runs long",
            "good well into the night",
        ],
        "zh": ["很晚去也合适", "夜里还能安排", "适合深夜过去"],
        "mixed": ["适合 late-night", "晚上很晚 still works", "夜里也 open"],
    },
    "outdoor_seating": {
        "en": ["where we can sit in the open air", "with tables outside", "letting us stay outdoors"],
        "zh": ["可以坐在室外", "有露天桌位", "能在户外待着"],
        "mixed": ["有 outdoor tables", "可以坐 outside", "露天 seating"],
    },
    "pet_friendly": {
        "en": [
            "where a dog is welcome",
            "comfortable for people bringing a pet",
            "friendly to four-legged company",
        ],
        "zh": ["可以带宠物", "带狗去也方便", "欢迎毛孩子"],
        "mixed": ["可以带 pet", "dog-friendly", "宠物 welcome"],
    },
    "quiet": {
        "en": ["where conversation is easy", "calm rather than noisy", "without a loud room"],
        "zh": ["说话不用提高嗓门", "环境别太吵", "比较清静"],
        "mixed": ["环境 quiet", "不要 loud", "适合安静聊天"],
    },
    "reservation_required": {
        "en": [
            "where booking ahead makes sense",
            "that takes advance reservations",
            "best planned with a booking",
        ],
        "zh": ["可以提前订位", "适合先预约", "需要预订也可以"],
        "mixed": ["可以 advance booking", "支持 reservation", "提前 book"],
    },
    "vegan_options": {
        "en": [
            "with genuinely plant-only choices",
            "where a vegan has options",
            "serving more than token plant-based food",
        ],
        "zh": ["纯植物饮食也有得选", "吃纯素不会没选择", "有不含动物制品的选项"],
        "mixed": ["有 vegan choices", "纯素 options", "plant-based 也能选"],
    },
    "wheelchair_accessible": {
        "en": [
            "with a step-free way in",
            "usable by someone in a wheelchair",
            "without stairs blocking access",
        ],
        "zh": ["轮椅可以顺利进入", "入口没有台阶障碍", "行动不便也能进"],
        "mixed": ["入口要 step-free", "wheelchair 可以进", "需要 accessible entrance"],
    },
}

NEGATION_PHRASES = {
    "budget_friendly": {"en": "not somewhere pricey", "zh": "不要价格很高的", "mixed": "不要 too pricey"},
    "quiet": {"en": "not a loud room", "zh": "不要吵闹的环境", "mixed": "不要 too loud"},
    "reservation_required": {
        "en": "not a walk-in gamble",
        "zh": "不想到了再碰运气",
        "mixed": "不要 walk-in gamble",
    },
    "wheelchair_accessible": {
        "en": "not blocked by stairs",
        "zh": "不要有台阶阻挡",
        "mixed": "不能被 stairs 挡住",
    },
}

VISIT_OPTIONS = [
    {"dayOfWeek": 5, "time": "20:30", "en": "Friday at 8:30 PM", "zh": "周五晚上八点半"},
    {"dayOfWeek": 6, "time": "21:30", "en": "Saturday at 9:30 PM", "zh": "周六晚上九点半"},
    {"dayOfWeek": 7, "time": "10:30", "en": "Sunday at 10:30 AM", "zh": "周日上午十点半"},
    {"dayOfWeek": 3, "time": "19:30", "en": "Wednesday at 7:30 PM", "zh": "周三晚上七点半"},
]

FAMILY_QUOTAS = {
    "semantic_alias_composition": {"en": 14, "zh": 12, "mixed": 4},
    "budget_party_boundary": {"en": 6, "zh": 4, "mixed": 2},
    "hours_time_boundary": {"en": 5, "zh": 4, "mixed": 1},
    "accessibility_required": {"en": 4, "zh": 3, "mixed": 1},
    "negation_exclusion": {"en": 4, "zh": 3, "mixed": 1},
    "identity_brand_geo": {"en": 3, "zh": 2, "mixed": 1},
    "noise_typo_transliteration": {"en": 4, "zh": 2, "mixed": 0},
}

GENERATOR_VERSION = "rag-v2-cases-v1"
LABEL_POLICY_VERSION = "derived-merchant-attributes-v1"
SEED = "20260831"


@dataclass(frozen=True)
class CaseSpec:
    family: str
    type_id: int
    neighborhood: str
    borough: str
    tags: tuple[str, str]
    shops: tuple[dict[str, Any], ...]
    hard_constraints: dict[str, Any]
    split: str

    @property
    def signature(self) -> str:
        raw = (
            f"{self.family}|{self.type_id}|{self.neighborhood}|"
            f"{','.join(self.tags)}|{_canonical_json(self.hard_constraints)}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_artifacts(data_directory: Path) -> tuple[dict, dict, dict]:
    shops = _read_json(data_directory / "shops.json")
    hours = _read_json(data_directory / "shop_business_hours.json")
    reviews = _read_json(data_directory / "shop_reviews.json")
    blogs = _read_json(data_directory / "blogs.json")
    blog_comments = _read_json(data_directory / "blog_comments.json")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))

    active_shops = [
        shop
        for shop in shops
        if shop.get("businessStatus", "OPERATIONAL") == "OPERATIONAL"
        and shop.get("externalId")
    ]
    hours_by_shop: dict[int, list[dict]] = defaultdict(list)
    for item in hours:
        hours_by_shop[int(item["shopId"])].append(item)
    security_by_shop = _security_documents_by_shop(reviews, blogs, blog_comments)
    names = _shops_by_normalized_name(active_shops)
    specs = _build_specs(active_shops, hours_by_shop, names)

    suites: dict[str, dict] = {}
    selected_intents: dict[str, set[str]] = {"dev": set(), "test": set()}
    for split in ("dev", "test"):
        cases = _select_and_render_cases(
            specs,
            split=split,
            all_shops=active_shops,
            hours_by_shop=hours_by_shop,
            security_by_shop=security_by_shop,
            names=names,
            selected_intents=selected_intents[split],
        )
        suites[split] = _suite(
            split=split,
            cases=cases,
            manifest=manifest,
        )

    fixtures = _adversarial_fixtures(
        shops_by_id={int(shop["id"]): shop for shop in active_shops},
        reviews=reviews,
        blogs=blogs,
        blog_comments=blog_comments,
        manifest=manifest,
    )
    fixtures_sha = fixtures["fixtureSha256"]
    split_isolation = _split_isolation(suites["dev"], suites["test"])
    for suite in suites.values():
        suite["adversarialFixtureSha256"] = fixtures_sha
        suite["evaluationDesign"] = {
            "languageSlices": "observational-unpaired-intents",
            "outOfDictionaryChallenge": (
                "phrase-bank provenance; not a guarantee that canonical_tags misses every target"
            ),
            "holdout": "committed-policy-holdout-not-secret",
            "semanticAliasRuleCoverage": _semantic_alias_rule_coverage(suite["cases"]),
        }
        suite["splitIsolation"] = split_isolation
        suite["hardNegativeCoverage"] = _hard_negative_coverage(suite["cases"])
        suite["suiteContractSha256"] = suite_contract_sha256(suite)
    return suites["dev"], suites["test"], fixtures


def _build_specs(
    shops: list[dict],
    hours_by_shop: dict[int, list[dict]],
    names: dict[str, list[dict]],
) -> list[CaseSpec]:
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for shop in shops:
        groups[(int(shop["typeId"]), str(shop["neighborhood"]))].append(shop)

    specs: list[CaseSpec] = []
    for (type_id, neighborhood), _rows in sorted(groups.items()):
        candidate_rows = [
            shop
            for shop in shops
            if int(shop["typeId"]) == type_id
            and _neighborhood_matches(str(shop["neighborhood"]), neighborhood)
        ]
        if not 12 <= len(candidate_rows) <= 100:
            continue
        borough_counts = Counter(str(row.get("borough") or "") for row in candidate_rows)
        borough = borough_counts.most_common(1)[0][0]
        split = _split_for_group(type_id, neighborhood)
        tag_rows: dict[str, set[int]] = defaultdict(set)
        for row in candidate_rows:
            for tag in row.get("tags") or []:
                if tag in TAG_PHRASES:
                    tag_rows[tag].add(int(row["id"]))
        tag_pairs = [
            pair
            for pair in itertools.combinations(sorted(tag_rows), 2)
            if len(tag_rows[pair[0]] & tag_rows[pair[1]]) >= 2
        ]
        for tags in tag_pairs:
            for family in FAMILY_QUOTAS:
                hard = _hard_constraints_for_family(
                    family,
                    type_id=type_id,
                    neighborhood=neighborhood,
                    borough=borough,
                    tags=tags,
                    rows=candidate_rows,
                    hours_by_shop=hours_by_shop,
                    names=names,
                )
                if hard is None:
                    continue
                judgments = _judgments(candidate_rows, tags, hard, hours_by_shop)
                if sum(item["relevance"] >= 2 for item in judgments) < 2:
                    continue
                specs.append(
                    CaseSpec(
                        family=family,
                        type_id=type_id,
                        neighborhood=neighborhood,
                        borough=borough,
                        tags=tags,
                        shops=tuple(sorted(candidate_rows, key=lambda row: int(row["id"]))),
                        hard_constraints=hard,
                        split=split,
                    )
                )
    return specs


def _hard_constraints_for_family(
    family: str,
    *,
    type_id: int,
    neighborhood: str,
    borough: str,
    tags: tuple[str, str],
    rows: list[dict],
    hours_by_shop: dict[int, list[dict]],
    names: dict[str, list[dict]],
) -> dict[str, Any] | None:
    hard: dict[str, Any] = {
        "category": CATEGORY_NAMES[type_id],
        "neighborhood": neighborhood,
        "borough": borough,
        "businessStatus": "OPERATIONAL",
        "maxPricePerPersonCents": None,
        "openAt": None,
        "requiredTags": [],
        "excludedTags": [],
    }
    matching = [row for row in rows if set(tags) <= set(row.get("tags") or [])]
    if family == "budget_party_boundary":
        prices = sorted(
            int(row["avgPriceCents"])
            for row in matching
            if isinstance(row.get("avgPriceCents"), int)
        )
        if len(prices) < 2:
            return None
        threshold = prices[min(2, len(prices) - 1)]
        if not any(
            row.get("avgPriceCents") is None
            or int(row["avgPriceCents"]) > threshold
            for row in rows
        ):
            return None
        hard["maxPricePerPersonCents"] = threshold
    elif family == "hours_time_boundary":
        selected_visit = None
        for visit in VISIT_OPTIONS:
            open_matching = [
                row
                for row in matching
                if _is_open(hours_by_shop.get(int(row["id"]), []), visit)
            ]
            closed_rows = [
                row
                for row in rows
                if not _is_open(hours_by_shop.get(int(row["id"]), []), visit)
            ]
            if len(open_matching) >= 2 and len(closed_rows) >= 2:
                selected_visit = {"dayOfWeek": visit["dayOfWeek"], "time": visit["time"]}
                break
        if selected_visit is None:
            return None
        hard["openAt"] = selected_visit
    elif family == "accessibility_required":
        if "wheelchair_accessible" not in tags:
            return None
        if not any("wheelchair_accessible" not in set(row.get("tags") or []) for row in rows):
            return None
        hard["requiredTags"] = ["wheelchair_accessible"]
    elif family == "negation_exclusion":
        if not any(tag in NEGATION_PHRASES for tag in tags):
            return None
    elif family == "identity_brand_geo":
        has_other_branch = any(
            len(names.get(_normalized_name(str(row.get("name") or "")), [])) > 1
            for row in rows
        )
        if not has_other_branch:
            return None
    return hard


def _select_and_render_cases(
    specs: list[CaseSpec],
    *,
    split: str,
    all_shops: list[dict],
    hours_by_shop: dict[int, list[dict]],
    security_by_shop: dict[int, set[str]],
    names: dict[str, list[dict]],
    selected_intents: set[str],
) -> list[dict]:
    cases: list[dict] = []
    signature_usage: Counter[str] = Counter()
    category_usage: Counter[int] = Counter()
    neighborhood_usage: Counter[str] = Counter()
    tag_usage: Counter[str] = Counter()

    for family, language_quotas in FAMILY_QUOTAS.items():
        family_specs = [item for item in specs if item.split == split and item.family == family]
        if not family_specs:
            raise ValueError(f"No eligible {family} specs for {split}.")
        for language in ("en", "zh", "mixed"):
            for sequence in range(language_quotas[language]):
                ordered = sorted(
                    family_specs,
                    key=lambda item: (
                        signature_usage[item.signature],
                        category_usage[item.type_id],
                        neighborhood_usage[item.neighborhood],
                        sum(tag_usage[tag] for tag in item.tags),
                        item.signature,
                    ),
                )
                spec = next(
                    (
                        item
                        for item in ordered
                        if f"{split}:{item.signature}" not in selected_intents
                        or signature_usage[item.signature] < 3
                    ),
                    None,
                )
                if spec is None:
                    raise ValueError(f"Could not select {family}/{language} case {sequence} for {split}.")
                signature_usage[spec.signature] += 1
                category_usage[spec.type_id] += 1
                neighborhood_usage[spec.neighborhood] += 1
                tag_usage.update(spec.tags)
                selected_intents.add(f"{split}:{spec.signature}")
                case_index = len(cases) + 1
                cases.append(
                    _render_case(
                        spec,
                        split=split,
                        language=language,
                        case_index=case_index,
                        variant=signature_usage[spec.signature],
                        all_shops=all_shops,
                        hours_by_shop=hours_by_shop,
                        security_by_shop=security_by_shop,
                        names=names,
                    )
                )

    cases.sort(key=lambda item: item["id"])
    if len(cases) != 80:
        raise ValueError(f"Expected 80 {split} cases, built {len(cases)}.")
    return cases


def _render_case(
    spec: CaseSpec,
    *,
    split: str,
    language: str,
    case_index: int,
    variant: int,
    all_shops: list[dict],
    hours_by_shop: dict[int, list[dict]],
    security_by_shop: dict[int, set[str]],
    names: dict[str, list[dict]],
) -> dict:
    query, template_id, code_switch_terms = _query(spec, language, case_index + variant)
    hard = spec.hard_constraints
    constraints: dict[str, Any] = {
        "query": query,
        "category": CATEGORY_NAMES[spec.type_id],
        "neighborhood": spec.neighborhood,
        "party_size": 2,
        "result_limit": 10,
    }
    if hard["maxPricePerPersonCents"] is not None:
        constraints["budget_cents"] = int(hard["maxPricePerPersonCents"]) * 2
    if hard["openAt"] is not None:
        visit = _visit_label(hard["openAt"])
        constraints["visit_time"] = visit["en"]
    if hard["requiredTags"]:
        constraints["desired_tags"] = list(hard["requiredTags"])

    judgments = _judgments(list(spec.shops), spec.tags, hard, hours_by_shop)
    hard_negatives = _hard_negatives(
        spec,
        all_shops=all_shops,
        judgments=judgments,
        hours_by_shop=hours_by_shop,
        names=names,
    )
    relevant = [item for item in judgments if item["relevance"] >= 2]
    if not relevant:
        raise ValueError(f"{spec.signature} has no relevant judgments.")

    forbidden = sorted(
        {
            document_id
            for judgment in judgments
            for document_id in security_by_shop.get(int(judgment["shopId"]), set())
        }
    )
    challenges = [spec.family, "hard_negative", "out_of_dictionary_paraphrase"]
    if forbidden:
        challenges.append("security_decoy")
    if spec.family == "identity_brand_geo":
        challenges.extend(["brand_duplicate", "cross_borough"])
    if spec.family == "noise_typo_transliteration":
        challenges.extend(["typo", "conversational_query"])
    if spec.family == "negation_exclusion":
        challenges.append("negative_expression")
    if spec.family in {"budget_party_boundary", "hours_time_boundary", "accessibility_required"}:
        challenges.append("hard_constraint_boundary")

    return {
        "id": f"{split}-{language}-{case_index:03d}",
        "intentGroup": f"intent-{spec.signature}",
        "split": split,
        "language": language,
        "scenario": spec.family,
        "query": query,
        "challengeTypes": sorted(set(challenges)),
        "constraints": constraints,
        "preferenceTags": list(spec.tags),
        "hardConstraints": hard,
        "judgments": judgments,
        "hardNegatives": hard_negatives,
        "forbiddenDocumentIds": forbidden,
        "metadata": {
            "templateId": template_id,
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "judgmentCompleteness": "complete-for-structured-candidate-pool",
            "candidatePoolSize": len(judgments),
            "codeSwitchTerms": code_switch_terms,
        },
    }


def _judgments(
    rows: list[dict],
    preference_tags: tuple[str, str],
    hard_constraints: dict[str, Any],
    hours_by_shop: dict[int, list[dict]],
) -> list[dict]:
    judgments = []
    for row in sorted(rows, key=lambda item: str(item["externalId"])):
        violations, unknown = _hard_constraint_violations(
            row,
            hard_constraints,
            hours_by_shop.get(int(row["id"]), []),
        )
        matched = sorted(set(preference_tags) & set(row.get("tags") or []))
        if violations:
            relevance = 0
        elif len(matched) == len(preference_tags):
            relevance = 3
        elif matched:
            relevance = 2
        else:
            relevance = 1
        judgments.append(
            {
                "shopId": int(row["id"]),
                "externalId": str(row["externalId"]),
                "relevance": relevance,
                "matchedPreferences": matched,
                "hardConstraintViolations": violations,
                "hardConstraintUnknowns": unknown,
                "negativeType": _negative_type(relevance, violations),
            }
        )
    return judgments


def _hard_negatives(
    spec: CaseSpec,
    *,
    all_shops: list[dict],
    judgments: list[dict],
    hours_by_shop: dict[int, list[dict]],
    names: dict[str, list[dict]],
) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()

    def add(row: dict, reasons: list[str], negative_type: str) -> None:
        external_id = str(row.get("externalId") or "")
        if not external_id or external_id in seen or len(buckets[negative_type]) >= 2:
            return
        seen.add(external_id)
        buckets[negative_type].append(
            {
                "shopId": int(row["id"]),
                "externalId": external_id,
                "negativeType": negative_type,
                "hardConstraintViolations": sorted(set(reasons)),
            }
        )

    rows_by_id = {int(row["id"]): row for row in spec.shops}
    for judgment in judgments:
        if judgment["relevance"] == 0:
            add(
                rows_by_id[int(judgment["shopId"])],
                list(judgment["hardConstraintViolations"]),
                "same-category-same-neighborhood-hard-violation",
            )

    for row in sorted(all_shops, key=lambda item: str(item["externalId"])):
        if (
            _neighborhood_matches(str(row["neighborhood"]), spec.neighborhood)
            and int(row["typeId"]) != spec.type_id
        ):
            add(row, ["category"], "same-neighborhood-wrong-category")

    for row in sorted(all_shops, key=lambda item: str(item["externalId"])):
        if (
            int(row["typeId"]) == spec.type_id
            and not _neighborhood_matches(str(row["neighborhood"]), spec.neighborhood)
        ):
            reason = "borough" if row.get("borough") != spec.borough else "neighborhood"
            add(row, [reason], "same-category-wrong-region")

    for source in spec.shops:
        branches = names.get(_normalized_name(str(source.get("name") or "")), [])
        for branch in sorted(branches, key=lambda item: str(item["externalId"])):
            if int(branch["id"]) == int(source["id"]):
                continue
            violations, _ = _hard_constraint_violations(
                branch,
                spec.hard_constraints,
                hours_by_shop.get(int(branch["id"]), []),
            )
            if violations:
                add(branch, violations, "same-brand-wrong-branch")
    ordered_types = (
        "same-category-same-neighborhood-hard-violation",
        "same-brand-wrong-branch",
        "same-neighborhood-wrong-category",
        "same-category-wrong-region",
    )
    return [item for negative_type in ordered_types for item in buckets[negative_type]][:8]


def _hard_constraint_violations(
    shop: dict,
    hard: dict[str, Any],
    hours: list[dict],
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    unknown: list[str] = []
    if CATEGORY_NAMES.get(int(shop["typeId"])) != hard["category"]:
        violations.append("category")
    if not _neighborhood_matches(
        str(shop.get("neighborhood") or ""), str(hard["neighborhood"])
    ):
        violations.append("neighborhood")
    if hard.get("borough") and str(shop.get("borough") or "") != hard["borough"]:
        violations.append("borough")
    if str(shop.get("businessStatus") or "OPERATIONAL") != hard["businessStatus"]:
        violations.append("business_status")
    max_price = hard.get("maxPricePerPersonCents")
    if max_price is not None:
        price = shop.get("avgPriceCents")
        if not isinstance(price, int):
            violations.append("budget_unknown")
            unknown.append("budget")
        elif price > int(max_price):
            violations.append("budget")
    required_tags = set(hard.get("requiredTags") or [])
    missing = sorted(required_tags - set(shop.get("tags") or []))
    violations.extend(f"required_tag:{tag}" for tag in missing)
    excluded = sorted(set(hard.get("excludedTags") or []) & set(shop.get("tags") or []))
    violations.extend(f"excluded_tag:{tag}" for tag in excluded)
    open_at = hard.get("openAt")
    if open_at is not None and not _is_open(hours, open_at):
        if not hours:
            unknown.append("business_hours")
            violations.append("business_hours_unknown")
        else:
            violations.append("closed_at_visit")
    return sorted(set(violations)), sorted(set(unknown))


def _is_open(hours: list[dict], visit: dict[str, Any]) -> bool:
    row = next(
        (item for item in hours if int(item.get("dayOfWeek") or 0) == int(visit["dayOfWeek"])),
        None,
    )
    if row is None or row.get("closed") or not row.get("openTime") or not row.get("closeTime"):
        return False
    target = _minutes(str(visit["time"]))
    opening = _minutes(str(row["openTime"]))
    closing = _minutes(str(row["closeTime"]))
    if row.get("closesNextDay") or closing <= opening:
        return target >= opening or target < closing
    return opening <= target < closing


def _minutes(value: str) -> int:
    hour, minute, *_ = value.split(":")
    return int(hour) * 60 + int(minute)


def _negative_type(relevance: int, violations: list[str]) -> str | None:
    if relevance == 0:
        return "hard-constraint-violation" if violations else "irrelevant"
    if relevance == 1:
        return "weak-semantic-match"
    if relevance == 2:
        return "partial-preference-match"
    return None


def _query(spec: CaseSpec, language: str, index: int) -> tuple[str, str, list[str]]:
    phrases = [
        TAG_PHRASES[tag][language][(index + offset) % len(TAG_PHRASES[tag][language])]
        for offset, tag in enumerate(spec.tags)
    ]
    category_en = CATEGORY_NAMES[spec.type_id].lower()
    category_zh = CHINESE_CATEGORY_NAMES[spec.type_id]
    family = spec.family
    visit = _visit_label(spec.hard_constraints.get("openAt"))
    price = spec.hard_constraints.get("maxPricePerPersonCents")
    code_switch_terms = re.findall(r"[A-Za-z][A-Za-z-]+", " ".join(phrases)) if language == "mixed" else []

    if family == "negation_exclusion":
        phrases = [
            NEGATION_PHRASES.get(tag, {}).get(language, phrase)
            for tag, phrase in zip(spec.tags, phrases, strict=True)
        ]
    if language == "en":
        if family == "budget_party_boundary":
            query = (
                f"Two of us need {category_en} around {spec.neighborhood}; keep it at or below "
                f"${price / 100:g} each, and make it {phrases[0]} plus {phrases[1]}."
            )
        elif family == "hours_time_boundary":
            query = (
                f"What {category_en} in {spec.neighborhood} is actually open {visit['en']} "
                f"and is {phrases[0]} as well as {phrases[1]}?"
            )
        elif family == "accessibility_required":
            query = (
                f"Find {category_en} in {spec.neighborhood} that is {phrases[0]} and {phrases[1]}; "
                "wheelchair access is non-negotiable."
            )
        elif family == "identity_brand_geo":
            query = (
                f"Recommend the correct {spec.neighborhood} branch of {category_en}, not a same-name "
                f"location elsewhere; it should be {phrases[0]} and {phrases[1]}."
            )
        elif family == "noise_typo_transliteration":
            noisy_category = category_en.replace("restaurant", "restuarant").replace(
                "attractions", "attracions"
            )
            query = f"hey, any {noisy_category} nr {spec.neighborhood} thats {phrases[0]} + {phrases[1]}?"
        else:
            query = (
                f"I am looking around {spec.neighborhood} for {category_en} that is "
                f"{phrases[0]} and {phrases[1]}."
            )
    elif language == "zh":
        if family == "budget_party_boundary":
            query = (
                f"两个人想在 {spec.neighborhood} 找{category_zh}，每人最多 ${price / 100:g}，"
                f"希望{phrases[0]}，而且{phrases[1]}。"
            )
        elif family == "hours_time_boundary":
            query = (
                f"请找 {spec.neighborhood} 在{visit['zh']}确实营业的{category_zh}，"
                f"最好{phrases[0]}并且{phrases[1]}。"
            )
        elif family == "accessibility_required":
            query = (
                f"想去 {spec.neighborhood} 的{category_zh}，要{phrases[0]}并且{phrases[1]}；"
                "轮椅通行是硬性条件。"
            )
        elif family == "identity_brand_geo":
            query = (
                f"只要 {spec.neighborhood} 这家{category_zh}，别混入同名的其他分店；"
                f"希望{phrases[0]}并且{phrases[1]}。"
            )
        elif family == "noise_typo_transliteration":
            query = f"帮忙看看 {spec.neighborhood} 附近有没有{category_zh}，{phrases[0]} + {phrases[1]}那种？"
        else:
            query = f"想在 {spec.neighborhood} 找{category_zh}，希望{phrases[0]}，同时{phrases[1]}。"
    else:
        if family == "budget_party_boundary":
            query = (
                f"两个人在 {spec.neighborhood} 找 {category_en}，per person 不超过 ${price / 100:g}，"
                f"还要{phrases[0]}和{phrases[1]}。"
            )
        elif family == "hours_time_boundary":
            query = (
                f"找 {spec.neighborhood} 的 {category_en}，{visit['zh']}必须 still open，"
                f"而且{phrases[0]}、{phrases[1]}。"
            )
        elif family == "identity_brand_geo":
            query = (
                f"只推荐 {spec.neighborhood} 的正确 branch，别给同名外区 {category_en}；"
                f"需要{phrases[0]}和{phrases[1]}。"
            )
        else:
            query = (
                f"在 {spec.neighborhood} 找 {category_en}，需要{phrases[0]}，"
                f"同时{phrases[1]}。"
            )
    return query, f"{family}-{language}-v{index % 3 + 1}", sorted(set(code_switch_terms))


def _visit_label(open_at: dict[str, Any] | None) -> dict[str, str]:
    if open_at is None:
        return {"en": "", "zh": ""}
    return next(
        item
        for item in VISIT_OPTIONS
        if item["dayOfWeek"] == open_at["dayOfWeek"] and item["time"] == open_at["time"]
    )


def _security_documents_by_shop(
    reviews: list[dict],
    blogs: list[dict],
    blog_comments: list[dict],
) -> dict[int, set[str]]:
    values: dict[int, set[str]] = defaultdict(set)
    for review in reviews:
        if review.get("securityTest"):
            root_id = int(review.get("rootId") or review["id"])
            values[int(review["shopId"])].add(f"shop_review_thread:{root_id}")
    blog_shop = {int(blog["id"]): int(blog["shopId"]) for blog in blogs}
    for comment in blog_comments:
        if comment.get("securityTest"):
            values[blog_shop[int(comment["blogId"])]].add(f"blog_comment:{comment['id']}")
    return values


def _adversarial_fixtures(
    *,
    shops_by_id: dict[int, dict],
    reviews: list[dict],
    blogs: list[dict],
    blog_comments: list[dict],
    manifest: dict,
) -> dict:
    review = next(item for item in reviews if item.get("securityTest"))
    blog_by_id = {int(item["id"]): item for item in blogs}
    comment = next(item for item in blog_comments if item.get("securityTest"))
    review_shop = shops_by_id[int(review["shopId"])]
    comment_shop = shops_by_id[int(blog_by_id[int(comment["blogId"])]["shopId"])]
    current_version = manifest["dataVersion"]
    dataset_sha = manifest["datasetSha256"]
    documents = [
        {
            "fixtureId": "stale-version-decoy",
            "expectedDisposition": "excluded-by-data-version-filter",
            "document": {
                "document_id": "rag-v2-stale-version-decoy",
                "shop_id": int(review_shop["id"]),
                "content_type": "shop_review",
                "source_id": "rag-v2-stale-version-decoy",
                "text": "Stale evidence must never outrank the current corpus.",
                "data_version": "nyc-real-stale-v0",
                "dataset_sha256": dataset_sha,
                "shop_external_id": review_shop["externalId"],
                "security_test": False,
            },
        },
        {
            "fixtureId": "security-review-decoy",
            "expectedDisposition": "excluded-by-security-filter",
            "document": {
                "document_id": f"rag-v2-security-review:{review['id']}",
                "shop_id": int(review_shop["id"]),
                "content_type": "shop_review",
                "source_id": f"rag-v2-security-review:{review['id']}",
                "text": str(review["content"]),
                "data_version": current_version,
                "dataset_sha256": dataset_sha,
                "shop_external_id": review_shop["externalId"],
                "security_test": True,
            },
        },
        {
            "fixtureId": "security-blog-comment-decoy",
            "expectedDisposition": "excluded-by-security-filter",
            "document": {
                "document_id": f"rag-v2-security-blog-comment:{comment['id']}",
                "shop_id": int(comment_shop["id"]),
                "content_type": "blog_comment",
                "source_id": f"rag-v2-security-blog-comment:{comment['id']}",
                "text": str(comment["content"]),
                "data_version": current_version,
                "dataset_sha256": dataset_sha,
                "shop_external_id": comment_shop["externalId"],
                "security_test": True,
            },
        },
    ]
    fixture = {
        "schemaVersion": 1,
        "suite": "rag-v2-adversarial-documents-v1",
        "dataVersion": current_version,
        "datasetSha256": dataset_sha,
        "documents": documents,
    }
    fixture["fixtureSha256"] = fixture_contract_sha256(fixture)
    return fixture


def _suite(*, split: str, cases: list[dict], manifest: dict) -> dict:
    canonical = _canonical_json(cases)
    return {
        "schemaVersion": 2,
        "suite": "rag-v2-hard-negative-v1",
        "split": split,
        "retrievalVersion": "p12-rag-v1",
        "generatorVersion": GENERATOR_VERSION,
        "labelPolicyVersion": LABEL_POLICY_VERSION,
        "labelSource": "deterministic-derived-merchant-attributes",
        "adjudicationStatus": "not-human-adjudicated",
        "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"],
        "binaryRelevanceThreshold": 2,
        "allowedCitationSourceTypes": [
            "MIXED",
            "OPENSTREETMAP",
            "PUBLIC_SOURCE",
            "SYNTHETIC",
        ],
        "indexedDocuments": _expected_document_count(manifest),
        "caseCount": len(cases),
        "caseSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "languageCounts": dict(sorted(Counter(case["language"] for case in cases).items())),
        "scenarioCounts": dict(sorted(Counter(case["scenario"] for case in cases).items())),
        "cases": cases,
    }


def _semantic_alias_rule_coverage(cases: list[dict]) -> dict[str, int]:
    counts = Counter()
    for case in cases:
        if case["scenario"] != "semantic_alias_composition":
            continue
        recognized = len(
            set(canonical_tags(case["query"])) & set(case["preferenceTags"])
        )
        counts[f"recognizedTargetTags{recognized}"] += 1
    return dict(sorted(counts.items()))


def _hard_negative_coverage(cases: list[dict]) -> dict[str, int | str]:
    declared = 0
    in_structured_pool = 0
    for case in cases:
        judged = {item["externalId"] for item in case["judgments"]}
        hard_negative_ids = {
            item["externalId"] for item in case.get("hardNegatives") or []
        }
        declared += len(hard_negative_ids)
        in_structured_pool += len(judged & hard_negative_ids)
    return {
        "declared": declared,
        "inStructuredCandidatePool": in_structured_pool,
        "metricScope": "final-return leakage across structured filtering and ranking",
    }


def _split_isolation(dev: dict, test: dict) -> dict[str, int | bool]:
    dev_cases = dev["cases"]
    test_cases = test["cases"]
    dev_judged = {
        item["externalId"] for case in dev_cases for item in case["judgments"]
    }
    test_judged = {
        item["externalId"] for case in test_cases for item in case["judgments"]
    }
    dev_relevant = {
        item["externalId"]
        for case in dev_cases
        for item in case["judgments"]
        if int(item["relevance"]) >= int(dev["binaryRelevanceThreshold"])
    }
    test_relevant = {
        item["externalId"]
        for case in test_cases
        for item in case["judgments"]
        if int(item["relevance"]) >= int(test["binaryRelevanceThreshold"])
    }
    return {
        "intentGroupOverlap": len(
            {case["intentGroup"] for case in dev_cases}
            & {case["intentGroup"] for case in test_cases}
        ),
        "queryOverlap": len(
            {case["query"] for case in dev_cases}
            & {case["query"] for case in test_cases}
        ),
        "judgedMerchantOverlap": len(dev_judged & test_judged),
        "binaryRelevantMerchantOverlap": len(dev_relevant & test_relevant),
        "merchantDisjoint": not bool(dev_judged & test_judged),
    }


def _split_for_group(type_id: int, neighborhood: str) -> str:
    digest = hashlib.sha256(f"{SEED}|{type_id}|{neighborhood}".encode()).digest()
    return "dev" if digest[0] % 2 == 0 else "test"


def _shops_by_normalized_name(shops: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for shop in shops:
        name = _normalized_name(str(shop.get("name") or ""))
        if name:
            result[name].append(shop)
    return result


def _normalized_name(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", value.casefold()).split())


def _neighborhood_matches(actual: str, requested: str) -> bool:
    actual_label = _normalized_name(actual)
    requested_label = _normalized_name(requested)
    return bool(
        requested_label
        and (
            actual_label == requested_label
            or f" {requested_label} " in f" {actual_label} "
        )
    )


def _read_json(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array.")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


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
    parser = argparse.ArgumentParser(description="Build deterministic RAG v2 evaluation artifacts.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p13-full",
    )
    parser.add_argument("--output-directory", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    dev, test, fixtures = build_artifacts(args.dataset.resolve())
    args.output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "cases.dev.json": dev,
        "cases.test.json": test,
        "adversarial_documents.json": fixtures,
    }
    for filename, value in artifacts.items():
        (args.output_directory / filename).write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "outputDirectory": str(args.output_directory.resolve()),
                "dev": {"cases": dev["caseCount"], "sha256": dev["caseSha256"]},
                "test": {"cases": test["caseCount"], "sha256": test["caseSha256"]},
                "fixtures": fixtures["fixtureSha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
