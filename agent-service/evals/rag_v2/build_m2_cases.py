from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.rag_v2.build_cases import (
    LABEL_POLICY_VERSION,
    _judgments,
    _read_json,
    _security_documents_by_shop,
)
from evals.rag_v2.contract import (
    m2_candidate_universe_sha256,
    suite_contract_sha256,
)

M2_SUITE_NAME = "rag-v2-m2-global-retrieval-dev-v1"
M2_GENERATOR_VERSION = "rag-v2-m2-actual-structured-bounded-union-v2"
M2_JUDGMENT_POLICY_VERSION = "m2-actual-structured-bounded-retrieval-union-v2"
M2_CANDIDATE_UNIVERSE_FILENAME = "candidate_universe.m2.dev.json"
FROZEN_M1_DEV_SUITE_PATH = Path(__file__).resolve().parent / "cases.dev.json"
M1_DEV_IDENTITY_FIELDS = ("suite", "caseSha256", "suiteContractSha256")


def frozen_m1_dev_source_identity() -> dict[str, str]:
    suite = json.loads(FROZEN_M1_DEV_SUITE_PATH.read_text(encoding="utf-8"))
    return {field: str(suite[field]) for field in M1_DEV_IDENTITY_FIELDS}


def validate_frozen_m1_dev_source_suite(
    source_suite: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> None:
    """Require an internally consistent copy of the committed M1 Dev suite.

    ``trusted_source_suite`` exists only so isolated unit fixtures can exercise the bounded
    builder. Production callers and both CLIs deliberately omit it and bind to cases.dev.json.
    """

    if int(source_suite.get("schemaVersion") or 0) != 2 or source_suite.get("split") != "dev":
        raise ValueError("M2 must start from the frozen schema-v2 M1 Dev suite.")
    case_sha256 = hashlib.sha256(_canonical_json(source_suite.get("cases") or []).encode()).hexdigest()
    if source_suite.get("caseSha256") != case_sha256:
        raise ValueError("M2 source Dev suite has an invalid case SHA.")
    if source_suite.get("suiteContractSha256") != suite_contract_sha256(source_suite):
        raise ValueError("M2 source Dev suite has an invalid suite contract SHA.")
    trusted = trusted_source_suite
    if trusted is None:
        trusted = json.loads(FROZEN_M1_DEV_SUITE_PATH.read_text(encoding="utf-8"))
    expected = {field: trusted.get(field) for field in M1_DEV_IDENTITY_FIELDS}
    observed = {field: source_suite.get(field) for field in M1_DEV_IDENTITY_FIELDS}
    if observed != expected:
        raise ValueError("M2 source must match the committed frozen M1 Dev suite identity.")


def capture_candidate_universe(
    *,
    source_suite: dict[str, Any],
    results: list[dict[str, Any]],
    resolved_config: dict[str, Any],
    config_fingerprint: str,
    experiment_fingerprint: str,
    index_manifest_fingerprint: str,
    scoped_source_sha256: str,
    runtime_environment: dict[str, str],
    qdrant_server: dict[str, Any],
    candidate_limit: int,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze the bounded, actually returned M2 treatment candidates for labeling.

    This deliberately captures at most ``candidate_limit`` final merchants per case.  It is
    the first half of a two-pass protocol: capture, deterministically label the bounded union,
    then run both control and treatment against that frozen schema-v3 suite.
    """

    validate_frozen_m1_dev_source_suite(
        source_suite,
        trusted_source_suite=trusted_source_suite,
    )
    features = resolved_config.get("features") or {}
    retrieval = resolved_config.get("retrieval") or {}
    if retrieval.get("mode") != "global-hybrid" or features.get("globalRetrievalEnabled") is not True:
        raise ValueError("M2 candidate capture requires the explicit global-hybrid treatment.")
    fingerprints = {
        "config": config_fingerprint,
        "experiment": experiment_fingerprint,
        "index manifest": index_manifest_fingerprint,
        "scoped source": scoped_source_sha256,
    }
    for label, value in fingerprints.items():
        if not _is_sha256(value):
            raise ValueError(f"M2 candidate capture requires a valid {label} fingerprint.")
    if not runtime_environment.get("pythonVersion") or not runtime_environment.get(
        "qdrantClientVersion"
    ):
        raise ValueError("M2 candidate capture requires Python and qdrant-client identities.")
    if not isinstance(qdrant_server, dict) or not qdrant_server.get("mode"):
        raise ValueError("M2 candidate capture requires Qdrant Server metadata.")
    if len(results) != int(source_suite.get("caseCount") or 0):
        raise ValueError("Candidate capture requires a complete source-suite run.")

    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    observed_ids = [str(result["id"]) for result in results]
    if observed_ids != expected_ids:
        raise ValueError("Candidate capture result order/IDs differ from the source suite.")

    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    cases: list[dict[str, Any]] = []
    candidate_pairs = 0
    structured_candidate_pairs = 0
    for result in results:
        case_id = str(result["id"])
        returned = _validated_external_ids(
            [item.get("externalId") for item in result.get("orderedCandidates") or []],
            label=f"Candidate capture {case_id} treatment output",
            allow_empty=True,
        )
        if len(returned) > candidate_limit:
            raise ValueError(
                f"Candidate capture {case_id} returned {len(returned)} merchants; "
                f"the declared bound is {candidate_limit}."
            )
        trace = result.get("retrievalTrace")
        if not isinstance(trace, dict):
            raise ValueError(f"Candidate capture {case_id} is missing its retrieval trace.")
        structured_external_ids = _validated_external_ids(
            trace.get("structuredBranchExternalIds"),
            label=f"Candidate capture {case_id} structured branch",
            allow_empty=True,
        )
        source_judgment_ids = {
            str(item["externalId"])
            for item in source_by_id[case_id]["judgments"]
        }
        unknown_structured = sorted(set(structured_external_ids) - source_judgment_ids)
        if unknown_structured:
            raise ValueError(
                f"Candidate capture {case_id} structured branch is outside the committed "
                f"M1 Dev judgments: {unknown_structured[:3]}"
            )
        candidate_pairs += len(returned)
        structured_candidate_pairs += len(structured_external_ids)
        cases.append(
            {
                "id": case_id,
                "structuredBranchExternalIds": structured_external_ids,
                "returnedExternalIds": returned,
            }
        )

    fixture = {
        "schemaVersion": 1,
        "suite": "rag-v2-m2-candidate-universe-v1",
        "split": "dev",
        "sourceSuite": source_suite["suite"],
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "dataVersion": source_suite["dataVersion"],
        "datasetSha256": source_suite["datasetSha256"],
        "retrievalMode": "global-hybrid",
        "globalRetrievalEnabled": True,
        "candidateLimit": candidate_limit,
        "experimentFingerprint": experiment_fingerprint,
        "configFingerprint": config_fingerprint,
        "indexManifestFingerprint": index_manifest_fingerprint,
        "scopedSourceSha256": scoped_source_sha256,
        "runtimeEnvironment": runtime_environment,
        "qdrantServer": qdrant_server,
        "caseCount": len(cases),
        "structuredCandidatePairCount": structured_candidate_pairs,
        "candidatePairCount": candidate_pairs,
        "cases": cases,
    }
    fixture["fixtureSha256"] = m2_candidate_universe_sha256(fixture)
    return fixture


def build_m2_dev_suite(
    data_directory: Path,
    source_suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic M2 Dev suite from a bounded retrieval-output union."""

    _validate_inputs(
        data_directory,
        source_suite,
        candidate_universe,
        trusted_source_suite=trusted_source_suite,
    )
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
    structured_pairs = 0
    bounded_pairs = 0
    qdrant_only_pairs = 0
    relevant_structured_miss_pairs = 0
    for source_case in source_suite["cases"]:
        case_id = str(source_case["id"])
        structured_external_ids = list(
            universe_by_case[case_id]["structuredBranchExternalIds"]
        )
        structured_ids = set(structured_external_ids)
        observed_ids = list(universe_by_case[case_id]["returnedExternalIds"])
        union_ids = sorted(structured_ids | set(observed_ids))
        if len(union_ids) > len(structured_ids) + int(candidate_universe["candidateLimit"]):
            raise ValueError(f"M2 candidate union for {case_id} exceeds its declared bound.")
        missing = sorted(set(union_ids) - active.keys())
        if missing:
            raise ValueError(f"M2 candidate union for {case_id} references unknown merchants: {missing[:3]}")
        labeled = _judgments(
            [active[external_id] for external_id in union_ids],
            tuple(source_case["preferenceTags"]),
            source_case["hardConstraints"],
            hours_by_shop,
        )
        for judgment in labeled:
            external_id = str(judgment["externalId"])
            judgment["judgmentOrigin"] = (
                "structured-candidate-pool"
                if external_id in structured_ids
                else "observed-global-treatment-output"
            )
            if external_id not in structured_ids and int(judgment["relevance"]) >= int(
                source_suite["binaryRelevanceThreshold"]
            ):
                relevant_structured_miss_pairs += 1

        qdrant_only = sorted(set(observed_ids) - structured_ids)
        forbidden = sorted(
            {
                document_id
                for judgment in labeled
                for document_id in security_by_shop.get(int(judgment["shopId"]), set())
            }
        )
        case = json.loads(json.dumps(source_case))
        case["judgments"] = labeled
        case["forbiddenDocumentIds"] = forbidden
        case["metadata"] = {
            **(case.get("metadata") or {}),
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "judgmentCompleteness": (
                "complete-for-frozen-actual-structured-branch-plus-treatment-output-union"
            ),
            "structuredCandidateCount": len(structured_ids),
            "structuredCandidateExternalIds": structured_external_ids,
            "treatmentReturnedCount": len(observed_ids),
            "treatmentReturnedExternalIds": observed_ids,
            "qdrantOnlyJudgmentCount": len(qdrant_only),
            "qdrantOnlyJudgmentExternalIds": qdrant_only,
            "boundedJudgmentCount": len(labeled),
        }
        cases.append(case)
        structured_pairs += len(structured_ids)
        bounded_pairs += len(labeled)
        qdrant_only_pairs += len(qdrant_only)

    if qdrant_only_pairs == 0:
        raise ValueError("M2 treatment did not add any Qdrant-only merchant to the bounded union.")
    if relevant_structured_miss_pairs == 0:
        raise ValueError(
            "M2 bounded union contains no binary-relevant structured miss; rescue cannot be tested."
        )

    suite = json.loads(json.dumps(source_suite))
    suite.update(
        {
            "schemaVersion": 3,
            "suite": M2_SUITE_NAME,
            "split": "dev",
            "generatorVersion": M2_GENERATOR_VERSION,
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "adjudicationStatus": "deterministic-bounded-union-not-human-adjudicated",
            "cases": cases,
            "caseCount": len(cases),
            "languageCounts": dict(sorted(Counter(case["language"] for case in cases).items())),
            "scenarioCounts": dict(sorted(Counter(case["scenario"] for case in cases).items())),
            "evaluationDesign": {
                **source_suite["evaluationDesign"],
                "holdout": "m2-dev-only-new-hidden-holdout-required-for-promotion",
                "candidateJudgments": "bounded-actual-structured-and-treatment-output-union",
                "m1PolicyHoldoutUsed": False,
            },
            "judgmentContract": {
                "policyVersion": M2_JUDGMENT_POLICY_VERSION,
                "scope": "frozen-actual-structured-branch-plus-observed-treatment-top-k",
                "unjudgedReturnedPolicy": "fail-closed",
                "sourceSplit": "dev",
                "m1PolicyHoldoutUsed": False,
                "sourceSuite": source_suite["suite"],
                "sourceSuiteCaseSha256": source_suite["caseSha256"],
                "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
                "candidateUniverseFixture": M2_CANDIDATE_UNIVERSE_FILENAME,
                "candidateUniverseFixtureSha256": candidate_universe["fixtureSha256"],
                "candidateLimit": int(candidate_universe["candidateLimit"]),
                "experimentFingerprint": candidate_universe["experimentFingerprint"],
                "captureConfigFingerprint": candidate_universe["configFingerprint"],
                "captureIndexManifestFingerprint": candidate_universe[
                    "indexManifestFingerprint"
                ],
                "captureScopedSourceSha256": candidate_universe["scopedSourceSha256"],
                "captureRuntimeEnvironment": candidate_universe["runtimeEnvironment"],
                "captureQdrantServer": candidate_universe["qdrantServer"],
                "structuredJudgmentPairs": structured_pairs,
                "boundedJudgmentPairs": bounded_pairs,
                "observedTreatmentPairs": int(candidate_universe["candidatePairCount"]),
                "qdrantOnlyJudgmentPairs": qdrant_only_pairs,
                "binaryRelevantStructuredMissPairs": relevant_structured_miss_pairs,
                "fullCorpusMerchantCount": len(active),
                "fullCartesianPairsAvoided": len(cases) * len(active) - bounded_pairs,
            },
        }
    )
    suite["caseSha256"] = hashlib.sha256(_canonical_json(cases).encode()).hexdigest()
    suite["suiteContractSha256"] = suite_contract_sha256(suite)
    return suite


def _validate_inputs(
    data_directory: Path,
    source_suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> None:
    validate_frozen_m1_dev_source_suite(
        source_suite,
        trusted_source_suite=trusted_source_suite,
    )
    if int(candidate_universe.get("schemaVersion") or 0) != 1:
        raise ValueError("M2 candidate universe must use schemaVersion=1.")
    if candidate_universe.get("split") != "dev":
        raise ValueError("M2 candidate universe must be captured from Dev.")
    if (
        candidate_universe.get("retrievalMode") != "global-hybrid"
        or candidate_universe.get("globalRetrievalEnabled") is not True
    ):
        raise ValueError("M2 candidate universe is not an explicit global-hybrid capture.")
    if candidate_universe.get("fixtureSha256") != m2_candidate_universe_sha256(candidate_universe):
        raise ValueError("M2 candidate-universe fixture SHA is invalid.")
    if not isinstance(candidate_universe.get("runtimeEnvironment"), dict):
        raise ValueError("M2 candidate universe is missing its runtime environment.")
    if not isinstance(candidate_universe.get("qdrantServer"), dict):
        raise ValueError("M2 candidate universe is missing Qdrant Server metadata.")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))
    expected = {
        "sourceSuite": source_suite["suite"],
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"],
        "caseCount": int(source_suite["caseCount"]),
    }
    for field, value in expected.items():
        if candidate_universe.get(field) != value:
            raise ValueError(f"M2 candidate universe {field} does not match its source.")
    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    observed_ids = [str(case.get("id")) for case in candidate_universe.get("cases") or []]
    if observed_ids != expected_ids:
        raise ValueError("M2 candidate-universe case order/IDs differ from source Dev.")
    candidate_limit = int(candidate_universe.get("candidateLimit") or 0)
    if not 1 <= candidate_limit <= 10:
        raise ValueError("M2 candidate-universe candidateLimit must be between 1 and 10.")
    candidate_pairs = 0
    structured_candidate_pairs = 0
    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    for case in candidate_universe["cases"]:
        case_id = str(case["id"])
        returned = _validated_external_ids(
            case.get("returnedExternalIds"),
            label=f"M2 candidate universe {case_id} treatment output",
            allow_empty=True,
        )
        if len(returned) > candidate_limit:
            raise ValueError(f"M2 candidate universe {case_id} violates its bounded set.")
        structured = _validated_external_ids(
            case.get("structuredBranchExternalIds"),
            label=f"M2 candidate universe {case_id} structured branch",
            allow_empty=True,
        )
        source_judgment_ids = {
            str(item["externalId"])
            for item in source_by_id[case_id]["judgments"]
        }
        if not set(structured) <= source_judgment_ids:
            raise ValueError(
                f"M2 candidate universe {case_id} structured branch is outside "
                "the committed M1 Dev judgments."
            )
        candidate_pairs += len(returned)
        structured_candidate_pairs += len(structured)
    if candidate_pairs != int(candidate_universe.get("candidatePairCount") or -1):
        raise ValueError("M2 candidate-universe candidatePairCount is invalid.")
    if structured_candidate_pairs != int(
        candidate_universe.get("structuredCandidatePairCount", -1)
    ):
        raise ValueError("M2 candidate-universe structuredCandidatePairCount is invalid.")


def _validated_external_ids(
    value: Any,
    *,
    label: str,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} external IDs must be a list.")
    if not allow_empty and not value:
        raise ValueError(f"{label} external IDs must be non-empty.")
    if any(
        not isinstance(external_id, str)
        or not external_id
        or external_id.strip() != external_id
        for external_id in value
    ):
        raise ValueError(f"{label} contains a missing or invalid external ID.")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate external IDs.")
    return list(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def main() -> None:
    repository = Path(__file__).resolve().parents[3]
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build a bounded, fail-closed M2 Dev judgment suite.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p13-full",
    )
    parser.add_argument("--source-suite", type=Path, default=directory / "cases.dev.json")
    parser.add_argument("--candidate-universe", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    source_suite = json.loads(args.source_suite.read_text(encoding="utf-8"))
    universe = json.loads(args.candidate_universe.read_text(encoding="utf-8"))
    suite = build_m2_dev_suite(args.dataset.resolve(), source_suite, universe)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    suite_path = args.output_directory / "cases.m2.dev.json"
    universe_path = args.output_directory / M2_CANDIDATE_UNIVERSE_FILENAME
    adversarial_source = args.source_suite.parent / "adversarial_documents.json"
    adversarial_path = args.output_directory / "adversarial_documents.json"
    if not adversarial_source.is_file():
        raise FileNotFoundError("The source suite must have a sibling adversarial_documents.json fixture.")
    if suite_path.exists() or universe_path.exists() or adversarial_path.exists():
        raise FileExistsError("Refusing to overwrite a frozen M2 suite or candidate universe.")
    suite_path.write_text(json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    universe_path.write_text(json.dumps(universe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    adversarial_path.write_bytes(adversarial_source.read_bytes())
    print(
        json.dumps(
            {
                "status": "ok",
                "suite": str(suite_path.resolve()),
                "candidateUniverse": str(universe_path.resolve()),
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
