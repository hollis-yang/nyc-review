from __future__ import annotations

import hashlib
import json
from typing import Any

SUITE_CONTRACT_FIELDS = (
    "schemaVersion",
    "suite",
    "split",
    "retrievalVersion",
    "generatorVersion",
    "labelPolicyVersion",
    "labelSource",
    "adjudicationStatus",
    "dataVersion",
    "datasetSha256",
    "binaryRelevanceThreshold",
    "allowedCitationSourceTypes",
    "indexedDocuments",
    "caseCount",
    "caseSha256",
    "languageCounts",
    "scenarioCounts",
    "evaluationDesign",
    "splitIsolation",
    "hardNegativeCoverage",
    "adversarialFixtureSha256",
    "cases",
)

FIXTURE_CONTRACT_FIELDS = (
    "schemaVersion",
    "suite",
    "dataVersion",
    "datasetSha256",
    "documents",
)


def suite_contract_sha256(suite: dict[str, Any]) -> str:
    missing = [field for field in SUITE_CONTRACT_FIELDS if field not in suite]
    if missing:
        raise ValueError(f"Eval suite contract is missing fields: {', '.join(missing)}")
    contract = {field: suite[field] for field in SUITE_CONTRACT_FIELDS}
    return sha256_json(contract)


def fixture_contract_sha256(fixture: dict[str, Any]) -> str:
    missing = [field for field in FIXTURE_CONTRACT_FIELDS if field not in fixture]
    if missing:
        raise ValueError(f"Adversarial fixture contract is missing fields: {', '.join(missing)}")
    contract = {field: fixture[field] for field in FIXTURE_CONTRACT_FIELDS}
    return sha256_json(contract)


def sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
