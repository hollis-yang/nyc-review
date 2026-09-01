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

M2_SUITE_CONTRACT_FIELDS = (
    *SUITE_CONTRACT_FIELDS,
    "judgmentContract",
)

FIXTURE_CONTRACT_FIELDS = (
    "schemaVersion",
    "suite",
    "dataVersion",
    "datasetSha256",
    "documents",
)

M2_CANDIDATE_UNIVERSE_CONTRACT_FIELDS = (
    "schemaVersion",
    "suite",
    "split",
    "sourceSuite",
    "sourceSuiteCaseSha256",
    "sourceSuiteContractSha256",
    "dataVersion",
    "datasetSha256",
    "retrievalMode",
    "globalRetrievalEnabled",
    "candidateLimit",
    "experimentFingerprint",
    "configFingerprint",
    "indexManifestFingerprint",
    "scopedSourceSha256",
    "runtimeEnvironment",
    "qdrantServer",
    "caseCount",
    "structuredCandidatePairCount",
    "candidatePairCount",
    "cases",
)


def suite_contract_sha256(suite: dict[str, Any]) -> str:
    schema_version = int(suite.get("schemaVersion") or 0)
    fields = M2_SUITE_CONTRACT_FIELDS if schema_version in {3, 4, 5} else SUITE_CONTRACT_FIELDS
    missing = [field for field in fields if field not in suite]
    if missing:
        raise ValueError(f"Eval suite contract is missing fields: {', '.join(missing)}")
    contract = {field: suite[field] for field in fields}
    return sha256_json(contract)


def fixture_contract_sha256(fixture: dict[str, Any]) -> str:
    missing = [field for field in FIXTURE_CONTRACT_FIELDS if field not in fixture]
    if missing:
        raise ValueError(f"Adversarial fixture contract is missing fields: {', '.join(missing)}")
    contract = {field: fixture[field] for field in FIXTURE_CONTRACT_FIELDS}
    return sha256_json(contract)


def m2_candidate_universe_sha256(fixture: dict[str, Any]) -> str:
    missing = [field for field in M2_CANDIDATE_UNIVERSE_CONTRACT_FIELDS if field not in fixture]
    if missing:
        raise ValueError("M2 candidate-universe contract is missing fields: " + ", ".join(missing))
    contract = {field: fixture[field] for field in M2_CANDIDATE_UNIVERSE_CONTRACT_FIELDS}
    return sha256_json(contract)


def sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
