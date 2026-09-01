from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.domain.models import CandidateSet, EvidencePack, UserConstraints
from app.rag.query_rewriter import QueryRewritePlan
from evals.rag_v2.build_cases import (
    LABEL_POLICY_VERSION,
    _judgments,
    _read_json,
    _security_documents_by_shop,
)
from evals.rag_v2.build_m3_cases import (
    M3_JUDGMENT_POLICY_VERSION,
    M3_SUITE_NAME,
    m3_suite_contract_sha256,
    rewrite_config_fingerprint,
)
from evals.rag_v2.contract import SUITE_CONTRACT_FIELDS, sha256_json
from evals.rag_v2.m4_replay import (
    M4_PERFORMANCE_SCOPE,
    M4_REPLAY_VERSION,
    frozen_replay_contract_sha256,
    m4_replay_implementation_sha256,
    validate_frozen_case_artifact,
)
from evals.rag_v2.metrics import integrity_metrics

M4_SUITE_NAME = "rag-v2-m4-cross-encoder-rerank-dev-v1"
M4_GENERATOR_VERSION = "rag-v2-m4-frozen-pre-rerank-pool-v1"
M4_JUDGMENT_POLICY_VERSION = "m4-complete-frozen-pre-rerank-pool-v1"
M4_CANDIDATE_UNIVERSE_FILENAME = "candidate_universe.m4.dev.json"
M4_CANDIDATE_UNIVERSE_NAME = "rag-v2-m4-pre-rerank-candidate-universe-v1"
M4_SELECTION_LEAKAGE_WARNING = (
    "The complete M3 pre-rerank Top-30 pool is reused by both reranker arms, but this "
    "pooled Dev suite inherits M3 selection leakage and is not a hidden promotion holdout."
)
FROZEN_M3_DEV_SUITE_PATH = Path(__file__).resolve().parent / "m3" / "cases.m3.dev.json"

M4_CANDIDATE_UNIVERSE_CONTRACT_FIELDS = (
    "schemaVersion",
    "suite",
    "split",
    "sourceSuite",
    "sourceSuiteSchemaVersion",
    "sourceSuiteCaseSha256",
    "sourceSuiteContractSha256",
    "sourceJudgmentContractSha256",
    "dataVersion",
    "datasetSha256",
    "candidateLimit",
    "finalCandidateLimit",
    "experimentFingerprint",
    "captureConfigFingerprint",
    "captureResultFingerprint",
    "captureRerankerConfigFingerprint",
    "indexManifestFingerprint",
    "scopedSourceSha256",
    "sourceGitSha",
    "runtimeEnvironment",
    "runtimeEnvironmentFingerprint",
    "qdrantServer",
    "qdrantServerFingerprint",
    "embeddingIdentity",
    "rewriteConfigFingerprint",
    "rewriteCaptureProvider",
    "rewriteCaptureModel",
    "rewritePromptVersion",
    "rewritePromptFingerprint",
    "performanceScope",
    "replayVersion",
    "replayImplementationSha256",
    "replayArtifactContractSha256",
    "selectionLeakageWarning",
    "caseCount",
    "preRerankCandidatePairCount",
    "candidatePoolContractSha256",
    "cases",
)

_RERANKER_FEATURE_KEYS = frozenset(
    {
        "rerankerProvider",
        "rerankerEnabled",
        "rerankerModel",
        "rerankerModelVersion",
        "rerankerConfigFingerprint",
        "rerankerInputVersion",
        "rerankerInputBuilderFingerprint",
    }
)
_ZERO_CAPTURE_COUNTERS = (
    "embeddingFallbackCount",
    "retrievalFallbackCount",
    "retrievalIdentityConflictCount",
    "retrievalSafetyRejectionCount",
    "rewriteFallbackCount",
    "rewriteSafetyRejectionCount",
    "rerankerFallbackCount",
    "rerankerRetryCount",
    "rerankerFailureCount",
)
_POOL_ID_FIELDS = (
    "preRerankCandidateExternalIds",
    "preRerankExternalIds",
    "rerankerInputExternalIds",
)
_POOL_FINGERPRINT_FIELDS = (
    "preRerankPoolFingerprint",
    "preRerankCandidateFingerprint",
    "candidatePoolFingerprint",
)
_INPUT_FINGERPRINT_FIELDS = (
    "rerankerInputFingerprint",
    "rerankInputFingerprint",
    "rerankerInputsFingerprint",
)
_INPUT_VALUE_FIELDS = ("rerankerInputs", "rerankInputs")


def m4_suite_contract_sha256(suite: dict[str, Any]) -> str:
    """Hash every schema-v5 field that can affect labels or evaluation."""

    if int(suite.get("schemaVersion") or 0) != 5:
        raise ValueError("M4 suite contract requires schemaVersion=5.")
    fields = (*SUITE_CONTRACT_FIELDS, "judgmentContract")
    missing = [field for field in fields if field not in suite]
    if missing:
        raise ValueError("M4 suite contract is missing fields: " + ", ".join(missing))
    return sha256_json({field: suite[field] for field in fields})


def m4_candidate_universe_sha256(fixture: dict[str, Any]) -> str:
    missing = [field for field in M4_CANDIDATE_UNIVERSE_CONTRACT_FIELDS if field not in fixture]
    if missing:
        raise ValueError("M4 candidate-universe contract is missing fields: " + ", ".join(missing))
    return sha256_json({field: fixture[field] for field in M4_CANDIDATE_UNIVERSE_CONTRACT_FIELDS})


def m4_candidate_pool_contract_rows(
    cases: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(case["id"]),
            "preRerankCandidateExternalIds": list(case["preRerankCandidateExternalIds"]),
            "preRerankPoolFingerprint": case["preRerankPoolFingerprint"],
            "rerankerInputFingerprint": case["rerankerInputFingerprint"],
        }
        for case in cases
    ]


def m4_experiment_fingerprint(config: dict[str, Any]) -> str:
    """Bind every setting except the isolated heuristic-vs-learned reranker."""

    value = json.loads(json.dumps(config))
    value.pop("experimentControlFingerprint", None)
    value.pop("reranker", None)
    rewrite = value.get("queryRewrite") or {}
    rewrite.pop("executionMode", None)
    rewrite.pop("replayArtifactContractSha256", None)
    features = value.get("features") or {}
    for key in _RERANKER_FEATURE_KEYS:
        features.pop(key, None)
    features.pop("queryRewriteConfigFingerprint", None)
    return sha256_json(value)


def reranker_config_fingerprint(config: dict[str, Any]) -> str:
    reranker = config.get("reranker")
    if isinstance(reranker, dict):
        return sha256_json(reranker)
    provider = (config.get("features") or {}).get("rerankerProvider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("M4 resolved config must identify its reranker provider.")
    return sha256_json({"provider": provider})


def validate_frozen_m3_dev_source_suite(
    source_suite: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> None:
    """Require the frozen schema-v4 M3 Dev suite and reject policy holdouts."""

    if (
        int(source_suite.get("schemaVersion") or 0) != 4
        or source_suite.get("suite") != M3_SUITE_NAME
        or source_suite.get("split") != "dev"
    ):
        raise ValueError("M4 must start from the frozen schema-v4 M3 Dev suite.")
    cases = source_suite.get("cases") or []
    if source_suite.get("caseSha256") != sha256_json(cases):
        raise ValueError("M4 source M3 suite has an invalid case SHA.")
    if source_suite.get("suiteContractSha256") != m3_suite_contract_sha256(source_suite):
        raise ValueError("M4 source M3 suite has an invalid suite contract SHA.")
    contract = source_suite.get("judgmentContract")
    if (
        not isinstance(contract, dict)
        or contract.get("policyVersion") != M3_JUDGMENT_POLICY_VERSION
        or contract.get("sourceSplit") != "dev"
        or contract.get("m1PolicyHoldoutUsed") is not False
        or contract.get("m1PolicyHoldoutForbidden") is not True
    ):
        raise ValueError("M4 may not consume or derive labels from the M1 Test holdout.")

    trusted = trusted_source_suite
    if trusted is None:
        trusted = json.loads(FROZEN_M3_DEV_SUITE_PATH.read_text(encoding="utf-8"))
    identity_fields = ("suite", "caseSha256", "suiteContractSha256")
    if any(source_suite.get(field) != trusted.get(field) for field in identity_fields):
        raise ValueError("M4 source must match the committed frozen M3 Dev suite identity.")
    if sha256_json(contract) != sha256_json(trusted.get("judgmentContract") or {}):
        raise ValueError("M4 source judgment contract differs from frozen M3 Dev.")


def capture_m4_candidate_universe(
    *,
    source_suite: dict[str, Any],
    capture_report: dict[str, Any],
    candidate_limit: int = 30,
    final_candidate_limit: int = 10,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze one shared pre-rerank pool and input fingerprint per Dev query."""

    validate_frozen_m3_dev_source_suite(
        source_suite,
        trusted_source_suite=trusted_source_suite,
    )
    _require_exact_integer(candidate_limit, label="M4 candidateLimit")
    _require_exact_integer(final_candidate_limit, label="M4 finalCandidateLimit")
    if candidate_limit != 30:
        raise ValueError("M4 freezes the pre-rerank Top-30; candidateLimit must equal 30.")
    if final_candidate_limit != 10:
        raise ValueError("M4 formal ranking uses Top-10; finalCandidateLimit must equal 10.")

    capture = _validate_capture_report(capture_report, source_suite=source_suite)
    cases: list[dict[str, Any]] = []
    pair_count = 0
    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    for result in capture["results"]:
        case_id = str(result["id"])
        source_case = source_by_id[case_id]
        constraints = UserConstraints.model_validate(source_case["constraints"])
        replay_artifact = validate_frozen_case_artifact(
            result.get("m4ReplayCapture"),
            expected_case_id=case_id,
            expected_constraints=constraints,
        )
        pool_ids, pool_fingerprint, input_fingerprint = extract_pre_rerank_contract(
            result,
            case_id=case_id,
        )
        if len(pool_ids) > candidate_limit:
            raise ValueError(f"M4 capture {case_id} exceeds the frozen Top-30 bound.")
        artifact_pool = CandidateSet.model_validate(replay_artifact["preRerankCandidateSet"])
        artifact_pool_ids = [item.external_id for item in artifact_pool.candidates]
        if (
            artifact_pool_ids != pool_ids
            or replay_artifact["preRerankMetadata"]["preRerankPoolFingerprint"] != pool_fingerprint
            or replay_artifact["preRerankMetadata"]["rerankerInputFingerprint"] != input_fingerprint
        ):
            raise ValueError(f"M4 capture {case_id} report differs from its frozen replay boundary.")
        cases.append(
            {
                "id": case_id,
                "preRerankCandidateExternalIds": pool_ids,
                "preRerankPoolFingerprint": pool_fingerprint,
                "rerankerInputFingerprint": input_fingerprint,
                "frozenM4ReplayArtifact": replay_artifact,
            }
        )
        pair_count += len(pool_ids)

    run = capture["run"]
    config = run["resolvedConfig"]
    runtime = run["runtimeEnvironment"]
    qdrant_server = capture["index"]["qdrantServer"]
    rewrite = config["queryRewrite"]
    replay_cases = [
        {
            "id": case["id"],
            "constraints": source_by_id[str(case["id"])]["constraints"],
            "metadata": {"frozenM4ReplayArtifact": case["frozenM4ReplayArtifact"]},
        }
        for case in cases
    ]
    replay_contract_sha = frozen_replay_contract_sha256(replay_cases)
    fixture = {
        "schemaVersion": 1,
        "suite": M4_CANDIDATE_UNIVERSE_NAME,
        "split": "dev",
        "sourceSuite": source_suite["suite"],
        "sourceSuiteSchemaVersion": 4,
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
        "dataVersion": source_suite["dataVersion"],
        "datasetSha256": source_suite["datasetSha256"],
        "candidateLimit": candidate_limit,
        "finalCandidateLimit": final_candidate_limit,
        "experimentFingerprint": run["m4ExperimentFingerprint"],
        "captureConfigFingerprint": run["configFingerprint"],
        "captureResultFingerprint": sha256_json(capture["results"]),
        "captureRerankerConfigFingerprint": run["rerankerConfigFingerprint"],
        "indexManifestFingerprint": capture["index"]["manifestFingerprint"],
        "scopedSourceSha256": run["scopedSource"]["sha256"],
        "sourceGitSha": run["git"]["sha"],
        "runtimeEnvironment": runtime,
        "runtimeEnvironmentFingerprint": sha256_json(runtime),
        "qdrantServer": qdrant_server,
        "qdrantServerFingerprint": sha256_json(qdrant_server),
        "embeddingIdentity": config["embedding"]["identity"],
        "rewriteConfigFingerprint": run["rewriteConfigFingerprint"],
        "rewriteCaptureProvider": rewrite["provider"],
        "rewriteCaptureModel": rewrite["model"],
        "rewritePromptVersion": rewrite["promptVersion"],
        "rewritePromptFingerprint": run["promptFingerprint"],
        "performanceScope": M4_PERFORMANCE_SCOPE,
        "replayVersion": M4_REPLAY_VERSION,
        "replayImplementationSha256": m4_replay_implementation_sha256(),
        "replayArtifactContractSha256": replay_contract_sha,
        "selectionLeakageWarning": M4_SELECTION_LEAKAGE_WARNING,
        "caseCount": len(cases),
        "preRerankCandidatePairCount": pair_count,
        "candidatePoolContractSha256": sha256_json(m4_candidate_pool_contract_rows(cases)),
        "cases": cases,
    }
    fixture["fixtureSha256"] = m4_candidate_universe_sha256(fixture)
    return fixture


def extract_pre_rerank_contract(
    result: Mapping[str, Any],
    *,
    case_id: str,
) -> tuple[list[str], str, str]:
    """Read stable M4 metadata while tolerating anticipated adapter field aliases."""

    containers = _metadata_containers(result)
    raw_ids = _first_present(containers, _POOL_ID_FIELDS)
    pool_ids = _validated_external_ids(
        raw_ids,
        label=f"M4 {case_id} pre-rerank pool",
        allow_empty=False,
    )
    canonical_pool_fingerprint = sha256_json(pool_ids)
    observed_pool_fingerprint = _first_present(
        containers,
        _POOL_FINGERPRINT_FIELDS,
        default=None,
    )
    if observed_pool_fingerprint is not None:
        if not _is_sha256(observed_pool_fingerprint):
            raise ValueError(f"M4 {case_id} pre-rerank pool fingerprint is invalid.")
        if observed_pool_fingerprint != canonical_pool_fingerprint:
            raise ValueError(f"M4 {case_id} pre-rerank pool fingerprint does not match IDs.")

    input_fingerprint = _first_present(
        containers,
        _INPUT_FINGERPRINT_FIELDS,
        default=None,
    )
    raw_inputs = _first_present(containers, _INPUT_VALUE_FIELDS, default=None)
    if raw_inputs is not None:
        if not isinstance(raw_inputs, list) or len(raw_inputs) != len(pool_ids):
            raise ValueError(f"M4 {case_id} reranker inputs must align with the frozen pool.")
        computed = sha256_json(raw_inputs)
        if input_fingerprint is None:
            input_fingerprint = computed
        elif input_fingerprint != computed:
            raise ValueError(f"M4 {case_id} reranker input fingerprint is invalid.")
    if not _is_sha256(input_fingerprint):
        raise ValueError(f"M4 {case_id} is missing a valid reranker input fingerprint.")
    return pool_ids, canonical_pool_fingerprint, str(input_fingerprint)


def build_m4_dev_suite(
    data_directory: Path,
    source_suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Label every merchant in the shared Top-30 pool, not just returned Top-10s."""

    validate_frozen_m3_dev_source_suite(
        source_suite,
        trusted_source_suite=trusted_source_suite,
    )
    _validate_candidate_universe(data_directory, source_suite, candidate_universe)

    shops = _read_json(data_directory / "shops.json")
    hours = _read_json(data_directory / "shop_business_hours.json")
    reviews = _read_json(data_directory / "shop_reviews.json")
    blogs = _read_json(data_directory / "blogs.json")
    blog_comments = _read_json(data_directory / "blog_comments.json")
    active = {
        str(shop["externalId"]): shop
        for shop in shops
        if shop.get("externalId") and shop.get("businessStatus", "OPERATIONAL") == "OPERATIONAL"
    }
    hours_by_shop: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in hours:
        hours_by_shop[int(row["shopId"])].append(row)
    security_by_shop = _security_documents_by_shop(reviews, blogs, blog_comments)
    universe_by_case = {str(item["id"]): item for item in candidate_universe["cases"]}

    cases: list[dict[str, Any]] = []
    pool_pairs = 0
    threshold = int(source_suite["binaryRelevanceThreshold"])
    relevant_pairs = 0
    for source_case in source_suite["cases"]:
        case_id = str(source_case["id"])
        universe_case = universe_by_case[case_id]
        pool_ids = list(universe_case["preRerankCandidateExternalIds"])
        missing = sorted(set(pool_ids) - active.keys())
        if missing:
            raise ValueError(f"M4 pre-rerank pool for {case_id} references unknown merchants: {missing[:3]}")
        labeled = _judgments(
            [active[external_id] for external_id in pool_ids],
            tuple(source_case["preferenceTags"]),
            source_case["hardConstraints"],
            hours_by_shop,
        )
        for judgment in labeled:
            judgment["judgmentOrigins"] = ["m4-shared-pre-rerank-top-30"]
            relevant_pairs += int(judgment["relevance"]) >= threshold
        forbidden = sorted(
            {
                document_id
                for judgment in labeled
                for document_id in security_by_shop.get(int(judgment["shopId"]), set())
            }
        )
        replay_artifact = validate_frozen_case_artifact(
            universe_case["frozenM4ReplayArtifact"],
            expected_case_id=case_id,
            expected_constraints=UserConstraints.model_validate(source_case["constraints"]),
        )
        frozen_pool = CandidateSet.model_validate(replay_artifact["preRerankCandidateSet"])
        frozen_evidence = EvidencePack.model_validate(replay_artifact["evidencePack"])
        for candidate in frozen_pool.candidates:
            corpus_shop = active[str(candidate.external_id)]
            if (
                int(corpus_shop["id"]) != candidate.shop_id
                or candidate.data_version != source_suite["dataVersion"]
            ):
                raise ValueError(f"M4 frozen candidate identity/version mismatch for {case_id}.")
        frozen_integrity, _ = integrity_metrics(
            candidates=frozen_pool.candidates,
            evidence=frozen_evidence,
            hard_constraints=source_case["hardConstraints"],
            suite=source_suite,
            forbidden_document_ids=set(forbidden),
        )
        evidence_failures = {
            field: frozen_integrity[field]
            for field in (
                "citationOwnershipMismatchCount",
                "citationExternalIdMismatchCount",
                "citationSourceMismatchCount",
                "securityLeakageCount",
                "versionMismatchCount",
            )
            if frozen_integrity[field] != 0
        }
        if frozen_integrity["evidenceCoverage"] != 1.0 or evidence_failures:
            raise ValueError(
                f"M4 frozen full-pool evidence contract failed for {case_id}: "
                f"coverage={frozen_integrity['evidenceCoverage']}, failures={evidence_failures}."
            )
        case = json.loads(json.dumps(source_case))
        case["judgments"] = labeled
        case["forbiddenDocumentIds"] = forbidden
        case["metadata"] = {
            **(case.get("metadata") or {}),
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "judgmentCompleteness": "complete-for-frozen-m4-pre-rerank-top-30-pool",
            "selectionLeakageWarning": M4_SELECTION_LEAKAGE_WARNING,
            "preRerankCandidateCount": len(pool_ids),
            "preRerankCandidateExternalIds": pool_ids,
            "preRerankPoolFingerprint": universe_case["preRerankPoolFingerprint"],
            "rerankerInputFingerprint": universe_case["rerankerInputFingerprint"],
            "frozenM4ReplayArtifact": universe_case["frozenM4ReplayArtifact"],
            "boundedJudgmentCount": len(labeled),
        }
        cases.append(case)
        pool_pairs += len(pool_ids)

    if relevant_pairs == 0:
        raise ValueError("M4 frozen candidate pools contain no binary-relevant merchant.")
    full_corpus_merchants = len(active)
    suite = json.loads(json.dumps(source_suite))
    suite.update(
        {
            "schemaVersion": 5,
            "suite": M4_SUITE_NAME,
            "split": "dev",
            "generatorVersion": M4_GENERATOR_VERSION,
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "adjudicationStatus": "deterministic-complete-pool-not-human-adjudicated",
            "cases": cases,
            "caseCount": len(cases),
            "languageCounts": dict(sorted(Counter(case["language"] for case in cases).items())),
            "scenarioCounts": dict(sorted(Counter(case["scenario"] for case in cases).items())),
            "evaluationDesign": {
                **source_suite["evaluationDesign"],
                "holdout": "m4-dev-only-new-hidden-holdout-required-for-promotion",
                "candidateJudgments": "complete-shared-pre-rerank-top-30-pool",
                "armCandidatePoolPolicy": "identical-frozen-replay",
                "performanceScope": M4_PERFORMANCE_SCOPE,
                "onlineEndToEndLatencyClaimAllowed": False,
                "selectionLeakageWarning": M4_SELECTION_LEAKAGE_WARNING,
                "m1PolicyHoldoutUsed": False,
            },
            "judgmentContract": {
                "policyVersion": M4_JUDGMENT_POLICY_VERSION,
                "scope": "complete-shared-pre-rerank-top-30-pool",
                "unjudgedReturnedPolicy": "fail-closed",
                "selectionLeakageWarning": M4_SELECTION_LEAKAGE_WARNING,
                "sourceSplit": "dev",
                "m1PolicyHoldoutUsed": False,
                "m1PolicyHoldoutForbidden": True,
                "sourceSuite": source_suite["suite"],
                "sourceSuiteSchemaVersion": 4,
                "sourceSuiteCaseSha256": source_suite["caseSha256"],
                "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
                "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
                "candidateUniverseFixture": M4_CANDIDATE_UNIVERSE_FILENAME,
                "candidateUniverseFixtureSha256": candidate_universe["fixtureSha256"],
                "candidatePoolContractSha256": candidate_universe["candidatePoolContractSha256"],
                "performanceScope": candidate_universe["performanceScope"],
                "replayVersion": candidate_universe["replayVersion"],
                "replayImplementationSha256": candidate_universe["replayImplementationSha256"],
                "replayArtifactContractSha256": candidate_universe["replayArtifactContractSha256"],
                "candidateLimit": candidate_universe["candidateLimit"],
                "finalCandidateLimit": candidate_universe["finalCandidateLimit"],
                "experimentFingerprint": candidate_universe["experimentFingerprint"],
                "captureConfigFingerprint": candidate_universe["captureConfigFingerprint"],
                "captureResultFingerprint": candidate_universe["captureResultFingerprint"],
                "captureRerankerConfigFingerprint": candidate_universe["captureRerankerConfigFingerprint"],
                "captureIndexManifestFingerprint": candidate_universe["indexManifestFingerprint"],
                "captureScopedSourceSha256": candidate_universe["scopedSourceSha256"],
                "captureSourceGitSha": candidate_universe["sourceGitSha"],
                "captureRuntimeEnvironment": candidate_universe["runtimeEnvironment"],
                "captureRuntimeEnvironmentFingerprint": candidate_universe["runtimeEnvironmentFingerprint"],
                "captureQdrantServer": candidate_universe["qdrantServer"],
                "captureQdrantServerFingerprint": candidate_universe["qdrantServerFingerprint"],
                "embeddingIdentity": candidate_universe["embeddingIdentity"],
                "rewriteConfigFingerprint": candidate_universe["rewriteConfigFingerprint"],
                "rewriteCaptureProvider": candidate_universe["rewriteCaptureProvider"],
                "rewriteCaptureModel": candidate_universe["rewriteCaptureModel"],
                "rewritePromptVersion": candidate_universe["rewritePromptVersion"],
                "rewritePromptFingerprint": candidate_universe["rewritePromptFingerprint"],
                "preRerankCandidatePairs": pool_pairs,
                "binaryRelevantCandidatePairs": relevant_pairs,
                "fullCorpusMerchantCount": full_corpus_merchants,
                "fullCartesianPairsAvoided": len(cases) * full_corpus_merchants - pool_pairs,
            },
        }
    )
    suite["caseSha256"] = sha256_json(cases)
    suite["suiteContractSha256"] = m4_suite_contract_sha256(suite)
    return suite


def write_m4_artifacts(
    output_directory: Path,
    *,
    suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    adversarial_source: Path,
) -> dict[str, Path]:
    if not adversarial_source.is_file():
        raise FileNotFoundError("The source suite must have a sibling adversarial fixture.")
    paths = {
        "suite": output_directory / "cases.m4.dev.json",
        "candidateUniverse": output_directory / M4_CANDIDATE_UNIVERSE_FILENAME,
        "adversarialDocuments": output_directory / "adversarial_documents.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("Refusing to overwrite a frozen M4 artifact.")
    output_directory.mkdir(parents=True, exist_ok=True)
    payloads = {
        "suite": (json.dumps(suite, indent=2, ensure_ascii=False) + "\n").encode(),
        "candidateUniverse": (json.dumps(candidate_universe, indent=2, ensure_ascii=False) + "\n").encode(),
        "adversarialDocuments": adversarial_source.read_bytes(),
    }
    opened: list[Path] = []
    try:
        for key, path in paths.items():
            with path.open("xb") as handle:
                handle.write(payloads[key])
            opened.append(path)
    except BaseException:
        for path in opened:
            path.unlink(missing_ok=True)
        raise
    return paths


def _validate_capture_report(
    report: dict[str, Any],
    *,
    source_suite: dict[str, Any],
) -> dict[str, Any]:
    if int(report.get("schemaVersion") or 0) < 4:
        raise ValueError("M4 pre-rerank capture report must use schemaVersion>=4.")
    suite = report.get("suite") or {}
    expected_suite = {
        "suite": source_suite["suite"],
        "split": "dev",
        "caseCount": source_suite["caseCount"],
        "caseSha256": source_suite["caseSha256"],
        "suiteContractSha256": source_suite["suiteContractSha256"],
        "judgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
    }
    if any(suite.get(field) != value for field, value in expected_suite.items()):
        raise ValueError("M4 capture does not use the frozen M3 Dev suite.")
    run = report.get("run") or {}
    if run.get("partial") is not False:
        raise ValueError("M4 capture must be complete.")
    _require_exact_integer(run.get("evaluatedCases"), label="M4 evaluatedCases")
    if run["evaluatedCases"] != source_suite["caseCount"]:
        raise ValueError("M4 capture result count differs from M3 Dev.")
    for counter in _ZERO_CAPTURE_COUNTERS:
        value = run.get(counter, 0)
        _require_exact_integer(value, label=f"M4 {counter}")
        if value:
            raise ValueError("M4 capture rejects fallback, retry, failure, or safety counters.")
    if (report.get("qualityGate") or {}).get("passed") is not True:
        raise ValueError("M4 capture must pass its per-run integrity gate.")
    results = report.get("results")
    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    if not isinstance(results, list) or [str(row.get("id")) for row in results] != expected_ids:
        raise ValueError("M4 capture result order/IDs differ from M3 Dev.")

    config = run.get("resolvedConfig")
    if not isinstance(config, dict) or run.get("configFingerprint") != sha256_json(config):
        raise ValueError("M4 capture config fingerprint is invalid.")
    experiment = m4_experiment_fingerprint(config)
    observed_experiment = run.get("m4ExperimentFingerprint", experiment)
    if observed_experiment != experiment:
        raise ValueError("M4 capture experiment fingerprint is invalid.")
    reranker_fingerprint = reranker_config_fingerprint(config)
    observed_reranker = run.get("rerankerConfigFingerprint", reranker_fingerprint)
    if observed_reranker != reranker_fingerprint:
        raise ValueError("M4 capture reranker config fingerprint is invalid.")
    _validate_enabled_m3_rewrite(run)
    _validate_source_runtime_index(report)
    rewrite = config["queryRewrite"]
    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    for result in results:
        case_id = str(result["id"])
        pool_ids, _, _ = extract_pre_rerank_contract(result, case_id=case_id)
        if len(pool_ids) > 30:
            raise ValueError(f"M4 capture {result['id']} exceeds Top-30.")
        artifact = validate_frozen_case_artifact(
            result.get("m4ReplayCapture"),
            expected_case_id=case_id,
            expected_constraints=UserConstraints.model_validate(source_by_id[case_id]["constraints"]),
        )
        plan = QueryRewritePlan.model_validate(artifact["rewritePlan"]["plan"])
        if (
            plan.trace.requested_provider != rewrite.get("provider")
            or plan.trace.requested_model != rewrite.get("model")
            or plan.trace.provider != rewrite.get("provider")
            or plan.trace.model != rewrite.get("model")
            or plan.trace.prompt_version != rewrite.get("promptVersion")
            or plan.trace.fallback_used
        ):
            raise ValueError(f"M4 capture {case_id} rewrite provider/model/prompt identity is invalid.")
    normalized_run = {
        **run,
        "m4ExperimentFingerprint": experiment,
        "rerankerConfigFingerprint": reranker_fingerprint,
    }
    return {**report, "run": normalized_run, "results": results}


def _validate_enabled_m3_rewrite(run: dict[str, Any]) -> None:
    config = run["resolvedConfig"]
    features = config.get("features") or {}
    rewrite = config.get("queryRewrite")
    if (
        (config.get("retrieval") or {}).get("mode") != "global-hybrid"
        or features.get("globalRetrievalEnabled") is not True
        or features.get("queryRewriteEnabled") is not True
        or not isinstance(rewrite, dict)
        or rewrite.get("enabled") is not True
        or rewrite.get("provider") in {None, "disabled"}
        or run.get("rewriteConfigFingerprint") != rewrite_config_fingerprint(config)
        or run.get("promptFingerprint") != rewrite.get("promptFingerprint")
        or not _is_sha256(run.get("promptFingerprint"))
    ):
        raise ValueError("M4 requires the accepted, enabled M3 retrieval and rewrite pipeline.")


def _validate_source_runtime_index(report: dict[str, Any]) -> None:
    run = report["run"]
    source = run.get("scopedSource")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("fileSha256"), dict)
        or source.get("sha256") != sha256_json(source["fileSha256"])
        or source.get("dirty") is not False
    ):
        raise ValueError("M4 requires a clean, valid scoped source snapshot.")
    git = run.get("git")
    if (
        not isinstance(git, dict)
        or not _is_hex_digest(git.get("sha"), lengths={40, 64})
        or git.get("dirty") is not False
    ):
        raise ValueError("M4 requires a clean Git source identity.")
    runtime = run.get("runtimeEnvironment")
    if not isinstance(runtime, dict) or not runtime.get("qdrantClientVersion"):
        raise ValueError("M4 capture is missing runtime identity.")
    index = report.get("index")
    if (
        not isinstance(index, dict)
        or index.get("lifecycleState") != "complete"
        or not _is_sha256(index.get("manifestFingerprint"))
        or not isinstance(index.get("qdrantServer"), dict)
        or not index["qdrantServer"].get("mode")
    ):
        raise ValueError("M4 capture requires the complete frozen Qdrant index.")
    identity = ((run.get("resolvedConfig") or {}).get("embedding") or {}).get("identity")
    if not _is_sha256(identity):
        raise ValueError("M4 capture is missing its embedding identity.")


def _validate_candidate_universe(
    data_directory: Path,
    source_suite: dict[str, Any],
    fixture: dict[str, Any],
) -> None:
    if fixture.get("schemaVersion") != 1 or fixture.get("suite") != M4_CANDIDATE_UNIVERSE_NAME:
        raise ValueError("M4 candidate universe uses an unsupported schema.")
    if fixture.get("fixtureSha256") != m4_candidate_universe_sha256(fixture):
        raise ValueError("M4 candidate-universe fixture SHA is invalid.")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))
    expected = {
        "split": "dev",
        "sourceSuite": source_suite["suite"],
        "sourceSuiteSchemaVersion": 4,
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
        "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"],
        "candidateLimit": 30,
        "finalCandidateLimit": 10,
        "caseCount": source_suite["caseCount"],
        "selectionLeakageWarning": M4_SELECTION_LEAKAGE_WARNING,
        "performanceScope": M4_PERFORMANCE_SCOPE,
        "replayVersion": M4_REPLAY_VERSION,
    }
    if any(fixture.get(field) != value for field, value in expected.items()):
        raise ValueError("M4 candidate universe differs from its source suite or corpus.")
    digest_fields = (
        "experimentFingerprint",
        "captureConfigFingerprint",
        "captureResultFingerprint",
        "captureRerankerConfigFingerprint",
        "indexManifestFingerprint",
        "scopedSourceSha256",
        "runtimeEnvironmentFingerprint",
        "qdrantServerFingerprint",
        "embeddingIdentity",
        "rewriteConfigFingerprint",
        "rewritePromptFingerprint",
        "candidatePoolContractSha256",
        "replayImplementationSha256",
        "replayArtifactContractSha256",
    )
    if any(not _is_sha256(fixture.get(field)) for field in digest_fields):
        raise ValueError("M4 candidate universe contains an invalid fingerprint.")
    if any(
        not isinstance(fixture.get(field), str) or not fixture[field].strip()
        for field in ("rewriteCaptureProvider", "rewriteCaptureModel")
    ):
        raise ValueError("M4 candidate universe has no captured rewrite identity.")
    if fixture["runtimeEnvironmentFingerprint"] != sha256_json(fixture["runtimeEnvironment"]):
        raise ValueError("M4 runtime fingerprint is invalid.")
    if fixture["qdrantServerFingerprint"] != sha256_json(fixture["qdrantServer"]):
        raise ValueError("M4 Qdrant fingerprint is invalid.")
    if not _is_hex_digest(fixture.get("sourceGitSha"), lengths={40, 64}):
        raise ValueError("M4 Git SHA is invalid.")

    cases = fixture.get("cases")
    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    if not isinstance(cases, list) or [str(case.get("id")) for case in cases] != expected_ids:
        raise ValueError("M4 candidate-universe case order/IDs differ from M3 Dev.")
    pair_count = 0
    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    replay_cases: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["id"])
        ids = _validated_external_ids(
            case.get("preRerankCandidateExternalIds"),
            label=f"M4 candidate universe {case_id}",
            allow_empty=False,
        )
        if len(ids) > 30:
            raise ValueError(f"M4 candidate universe {case_id} exceeds Top-30.")
        if case.get("preRerankPoolFingerprint") != sha256_json(ids):
            raise ValueError(f"M4 candidate universe {case_id} pool fingerprint is invalid.")
        if not _is_sha256(case.get("rerankerInputFingerprint")):
            raise ValueError(f"M4 candidate universe {case_id} input fingerprint is invalid.")
        artifact = validate_frozen_case_artifact(
            case.get("frozenM4ReplayArtifact"),
            expected_case_id=case_id,
            expected_constraints=UserConstraints.model_validate(source_by_id[case_id]["constraints"]),
        )
        artifact_pool = CandidateSet.model_validate(artifact["preRerankCandidateSet"])
        if [item.external_id for item in artifact_pool.candidates] != ids:
            raise ValueError(f"M4 candidate universe {case_id} artifact pool differs from contract.")
        replay_cases.append(
            {
                "id": case_id,
                "constraints": source_by_id[case_id]["constraints"],
                "metadata": {"frozenM4ReplayArtifact": artifact},
            }
        )
        pair_count += len(ids)
    if fixture.get("candidatePoolContractSha256") != sha256_json(m4_candidate_pool_contract_rows(cases)):
        raise ValueError("M4 candidate-pool contract SHA is invalid.")
    if fixture.get("replayArtifactContractSha256") != frozen_replay_contract_sha256(replay_cases):
        raise ValueError("M4 frozen replay artifact contract SHA is invalid.")
    if fixture.get("replayImplementationSha256") != m4_replay_implementation_sha256():
        raise ValueError("M4 replay implementation changed after candidate capture.")
    _require_exact_integer(
        fixture.get("preRerankCandidatePairCount"),
        label="M4 preRerankCandidatePairCount",
    )
    if fixture["preRerankCandidatePairCount"] != pair_count:
        raise ValueError("M4 candidate pair count is invalid.")


def _metadata_containers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = [result]
    trace = result.get("retrievalTrace")
    if isinstance(trace, Mapping):
        containers.append(trace)
    metadata = result.get("retrievalMetadata")
    if isinstance(metadata, Mapping):
        containers.append(metadata)
        for name in ("candidateDiscovery", "ranking", "candidatePool", "reranker"):
            child = metadata.get(name)
            if isinstance(child, Mapping):
                containers.append(child)
    return containers


def _first_present(
    containers: list[Mapping[str, Any]],
    fields: tuple[str, ...],
    *,
    default: Any = ...,
) -> Any:
    for container in containers:
        for field in fields:
            if field in container:
                return container[field]
    if default is not ...:
        return default
    raise ValueError("M4 report is missing metadata field: " + " or ".join(fields))


def _validated_external_ids(value: Any, *, label: str, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{label} external IDs must be a non-empty list.")
    if any(not isinstance(item, str) or not item or item.strip() != item for item in value):
        raise ValueError(f"{label} contains an invalid external ID.")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate external IDs.")
    return list(value)


def _require_exact_integer(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _is_sha256(value: Any) -> bool:
    return _is_hex_digest(value, lengths={64})


def _is_hex_digest(value: Any, *, lengths: set[int]) -> bool:
    if not isinstance(value, str) or len(value) not in lengths:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def main() -> None:
    repository = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Build the complete shared-pool schema-v5 M4 Dev judgment suite."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p13-full",
    )
    parser.add_argument("--source-suite", type=Path, default=FROZEN_M3_DEV_SUITE_PATH)
    parser.add_argument("--capture-report", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=30)
    parser.add_argument("--final-candidate-limit", type=int, default=10)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    source_suite = json.loads(args.source_suite.read_text(encoding="utf-8"))
    capture_report = json.loads(args.capture_report.read_text(encoding="utf-8"))
    universe = capture_m4_candidate_universe(
        source_suite=source_suite,
        capture_report=capture_report,
        candidate_limit=args.candidate_limit,
        final_candidate_limit=args.final_candidate_limit,
    )
    suite = build_m4_dev_suite(args.dataset.resolve(), source_suite, universe)
    paths = write_m4_artifacts(
        args.output_directory,
        suite=suite,
        candidate_universe=universe,
        adversarial_source=args.source_suite.parent / "adversarial_documents.json",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "suite": str(paths["suite"].resolve()),
                "candidateUniverse": str(paths["candidateUniverse"].resolve()),
                "caseSha256": suite["caseSha256"],
                "suiteContractSha256": suite["suiteContractSha256"],
                "judgmentContract": suite["judgmentContract"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
