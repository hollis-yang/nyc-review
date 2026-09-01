from __future__ import annotations

import argparse
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
from evals.rag_v2.contract import SUITE_CONTRACT_FIELDS, sha256_json, suite_contract_sha256

M3_SUITE_NAME = "rag-v2-m3-query-rewrite-dev-v1"
M3_GENERATOR_VERSION = "rag-v2-m3-structured-control-treatment-bounded-union-v1"
M3_JUDGMENT_POLICY_VERSION = "m3-structured-m2-control-m3-treatment-bounded-union-v1"
M3_CANDIDATE_UNIVERSE_FILENAME = "candidate_universe.m3.dev.json"
M3_CANDIDATE_UNIVERSE_NAME = "rag-v2-m3-candidate-universe-v1"
M3_SELECTION_LEAKAGE_WARNING = (
    "M2 control Top-K and M3 treatment Top-K participate in the bounded judgment union; "
    "this pooled Dev suite cannot be used as a hidden production-promotion holdout."
)
FROZEN_M2_DEV_SUITE_PATH = Path(__file__).resolve().parent / "m2" / "cases.m2.dev.json"

M3_CANDIDATE_UNIVERSE_CONTRACT_FIELDS = (
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
    "experimentFingerprint",
    "controlConfigFingerprint",
    "treatmentConfigFingerprint",
    "controlResultFingerprint",
    "treatmentResultFingerprint",
    "indexManifestFingerprint",
    "scopedSourceSha256",
    "sourceGitSha",
    "runtimeEnvironment",
    "runtimeEnvironmentFingerprint",
    "qdrantServer",
    "qdrantServerFingerprint",
    "embeddingIdentity",
    "controlRewriteConfigFingerprint",
    "treatmentRewriteConfigFingerprint",
    "treatmentPromptVersion",
    "treatmentPromptFingerprint",
    "selectionLeakageWarning",
    "caseCount",
    "structuredCandidatePairCount",
    "m2ControlTopKPairCount",
    "m3TreatmentTopKPairCount",
    "cases",
)

_REWRITE_FEATURE_KEYS = frozenset(
    {
        "queryRewriteProvider",
        "queryRewriteEnabled",
        "queryRewritePromptVersion",
        "queryRewritePromptFingerprint",
        "queryRewriteConfigFingerprint",
    }
)
_ZERO_CAPTURE_COUNTERS = (
    "embeddingFallbackCount",
    "retrievalFallbackCount",
    "retrievalIdentityConflictCount",
    "retrievalSafetyRejectionCount",
    "rewriteFallbackCount",
    "rewriteSafetyRejectionCount",
)


def m3_suite_contract_sha256(suite: dict[str, Any]) -> str:
    """Hash every schema-v4 suite field that can affect judgments or evaluation."""

    if int(suite.get("schemaVersion") or 0) != 4:
        raise ValueError("M3 suite contract requires schemaVersion=4.")
    fields = (*SUITE_CONTRACT_FIELDS, "judgmentContract")
    missing = [field for field in fields if field not in suite]
    if missing:
        raise ValueError("M3 suite contract is missing fields: " + ", ".join(missing))
    return sha256_json({field: suite[field] for field in fields})


def m3_candidate_universe_sha256(fixture: dict[str, Any]) -> str:
    missing = [
        field for field in M3_CANDIDATE_UNIVERSE_CONTRACT_FIELDS if field not in fixture
    ]
    if missing:
        raise ValueError("M3 candidate-universe contract is missing fields: " + ", ".join(missing))
    return sha256_json(
        {field: fixture[field] for field in M3_CANDIDATE_UNIVERSE_CONTRACT_FIELDS}
    )


def m3_experiment_fingerprint(config: dict[str, Any]) -> str:
    """Bind both arms after removing only the isolated rewrite configuration."""

    value = json.loads(json.dumps(config))
    value.pop("experimentControlFingerprint", None)
    value.pop("queryRewrite", None)
    features = value.get("features") or {}
    for key in _REWRITE_FEATURE_KEYS:
        features.pop(key, None)
    return sha256_json(value)


def rewrite_config_fingerprint(config: dict[str, Any]) -> str:
    rewrite = config.get("queryRewrite")
    if not isinstance(rewrite, dict):
        raise ValueError("M3 resolved config must include a queryRewrite object.")
    return sha256_json(rewrite)


def validate_frozen_m2_dev_source_suite(
    source_suite: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> None:
    """Require the committed schema-v3 M2 Dev suite and permanently reject M1 Test."""

    if int(source_suite.get("schemaVersion") or 0) != 3 or source_suite.get("split") != "dev":
        raise ValueError(
            "M3 must start from the frozen schema-v3 M2 Dev suite; the consumed M1 Test "
            "holdout is permanently forbidden."
        )
    cases = source_suite.get("cases") or []
    if source_suite.get("caseSha256") != _fingerprint(cases):
        raise ValueError("M3 source M2 suite has an invalid case SHA.")
    if source_suite.get("suiteContractSha256") != suite_contract_sha256(source_suite):
        raise ValueError("M3 source M2 suite has an invalid suite contract SHA.")
    judgment_contract = source_suite.get("judgmentContract")
    if not isinstance(judgment_contract, dict):
        raise ValueError("M3 source M2 suite is missing its bounded judgment contract.")
    if (
        judgment_contract.get("sourceSplit") != "dev"
        or judgment_contract.get("m1PolicyHoldoutUsed") is not False
        or (source_suite.get("evaluationDesign") or {}).get("m1PolicyHoldoutUsed") is not False
    ):
        raise ValueError("M3 may not consume or derive labels from the M1 Test holdout.")

    trusted = trusted_source_suite
    if trusted is None:
        trusted = json.loads(FROZEN_M2_DEV_SUITE_PATH.read_text(encoding="utf-8"))
    identity_fields = ("suite", "caseSha256", "suiteContractSha256")
    if any(source_suite.get(field) != trusted.get(field) for field in identity_fields):
        raise ValueError("M3 source must match the committed frozen M2 Dev suite identity.")
    if sha256_json(judgment_contract) != sha256_json(trusted.get("judgmentContract") or {}):
        raise ValueError("M3 source M2 judgment contract differs from the committed Dev suite.")


def capture_m3_candidate_universe(
    *,
    source_suite: dict[str, Any],
    control_report: dict[str, Any],
    treatment_report: dict[str, Any],
    candidate_limit: int,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze actual Structured IDs plus M2-control and M3-treatment Top-K outputs."""

    validate_frozen_m2_dev_source_suite(
        source_suite,
        trusted_source_suite=trusted_source_suite,
    )
    if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int):
        raise ValueError("M3 candidateLimit must be an integer.")
    if not 1 <= candidate_limit <= 10:
        raise ValueError("M3 candidateLimit must be between 1 and 10.")

    control = _validate_capture_report(
        control_report,
        source_suite=source_suite,
        arm="control",
    )
    treatment = _validate_capture_report(
        treatment_report,
        source_suite=source_suite,
        arm="treatment",
    )
    _validate_capture_pair(control, treatment)

    cases: list[dict[str, Any]] = []
    structured_pairs = 0
    control_pairs = 0
    treatment_pairs = 0
    for control_result, treatment_result in zip(
        control["results"], treatment["results"], strict=True
    ):
        case_id = str(control_result["id"])
        control_ids = _validated_external_ids(
            [item.get("externalId") for item in control_result.get("orderedCandidates") or []],
            label=f"M3 capture {case_id} M2 control Top-K",
            allow_empty=True,
        )
        treatment_ids = _validated_external_ids(
            [item.get("externalId") for item in treatment_result.get("orderedCandidates") or []],
            label=f"M3 capture {case_id} M3 treatment Top-K",
            allow_empty=True,
        )
        if len(control_ids) > candidate_limit or len(treatment_ids) > candidate_limit:
            raise ValueError(f"M3 capture {case_id} exceeds candidateLimit={candidate_limit}.")
        control_trace = control_result.get("retrievalTrace")
        treatment_trace = treatment_result.get("retrievalTrace")
        if not isinstance(control_trace, dict) or not isinstance(treatment_trace, dict):
            raise ValueError(f"M3 capture {case_id} is missing a retrieval trace.")
        control_structured = _validated_external_ids(
            control_trace.get("structuredBranchExternalIds"),
            label=f"M3 capture {case_id} control Structured branch",
            allow_empty=True,
        )
        treatment_structured = _validated_external_ids(
            treatment_trace.get("structuredBranchExternalIds"),
            label=f"M3 capture {case_id} treatment Structured branch",
            allow_empty=True,
        )
        if control_structured != treatment_structured:
            raise ValueError(
                f"M3 capture {case_id} Structured branch changed between rewrite arms."
            )
        source_case = next(case for case in source_suite["cases"] if str(case["id"]) == case_id)
        source_judgment_ids = {
            str(item["externalId"]) for item in source_case.get("judgments") or []
        }
        if not set(control_structured) <= source_judgment_ids:
            raise ValueError(
                f"M3 capture {case_id} Structured IDs fall outside frozen M2 judgments."
            )
        cases.append(
            {
                "id": case_id,
                "structuredBranchExternalIds": control_structured,
                "m2ControlReturnedExternalIds": control_ids,
                "m3TreatmentReturnedExternalIds": treatment_ids,
            }
        )
        structured_pairs += len(control_structured)
        control_pairs += len(control_ids)
        treatment_pairs += len(treatment_ids)

    control_run = control["run"]
    treatment_run = treatment["run"]
    control_config = control_run["resolvedConfig"]
    treatment_config = treatment_run["resolvedConfig"]
    runtime_environment = control_run["runtimeEnvironment"]
    qdrant_server = control["index"]["qdrantServer"]
    treatment_rewrite = treatment_config["queryRewrite"]
    fixture = {
        "schemaVersion": 1,
        "suite": M3_CANDIDATE_UNIVERSE_NAME,
        "split": "dev",
        "sourceSuite": source_suite["suite"],
        "sourceSuiteSchemaVersion": 3,
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
        "dataVersion": source_suite["dataVersion"],
        "datasetSha256": source_suite["datasetSha256"],
        "candidateLimit": candidate_limit,
        "experimentFingerprint": control_run["m3ExperimentFingerprint"],
        "controlConfigFingerprint": control_run["configFingerprint"],
        "treatmentConfigFingerprint": treatment_run["configFingerprint"],
        "controlResultFingerprint": _fingerprint(control["results"]),
        "treatmentResultFingerprint": _fingerprint(treatment["results"]),
        "indexManifestFingerprint": control["index"]["manifestFingerprint"],
        "scopedSourceSha256": control_run["scopedSource"]["sha256"],
        "sourceGitSha": control_run["git"]["sha"],
        "runtimeEnvironment": runtime_environment,
        "runtimeEnvironmentFingerprint": _fingerprint(runtime_environment),
        "qdrantServer": qdrant_server,
        "qdrantServerFingerprint": _fingerprint(qdrant_server),
        "embeddingIdentity": control_config["embedding"]["identity"],
        "controlRewriteConfigFingerprint": control_run["rewriteConfigFingerprint"],
        "treatmentRewriteConfigFingerprint": treatment_run["rewriteConfigFingerprint"],
        "treatmentPromptVersion": treatment_rewrite["promptVersion"],
        "treatmentPromptFingerprint": treatment_run["promptFingerprint"],
        "selectionLeakageWarning": M3_SELECTION_LEAKAGE_WARNING,
        "caseCount": len(cases),
        "structuredCandidatePairCount": structured_pairs,
        "m2ControlTopKPairCount": control_pairs,
        "m3TreatmentTopKPairCount": treatment_pairs,
        "cases": cases,
    }
    fixture["fixtureSha256"] = m3_candidate_universe_sha256(fixture)
    return fixture


def build_m3_dev_suite(
    data_directory: Path,
    source_suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply deterministic merchant-attribute labels to the bounded three-way union."""

    validate_frozen_m2_dev_source_suite(
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
    structured_pairs = 0
    control_pairs = 0
    treatment_pairs = 0
    bounded_pairs = 0
    treatment_only_pairs = 0
    relevant_treatment_only_pairs = 0
    threshold = int(source_suite["binaryRelevanceThreshold"])
    for source_case in source_suite["cases"]:
        case_id = str(source_case["id"])
        universe_case = universe_by_case[case_id]
        structured = list(universe_case["structuredBranchExternalIds"])
        control = list(universe_case["m2ControlReturnedExternalIds"])
        treatment = list(universe_case["m3TreatmentReturnedExternalIds"])
        structured_set = set(structured)
        control_set = set(control)
        treatment_set = set(treatment)
        union_ids = sorted(structured_set | control_set | treatment_set)
        maximum = len(structured_set) + 2 * int(candidate_universe["candidateLimit"])
        if len(union_ids) > maximum:
            raise ValueError(f"M3 bounded union for {case_id} exceeds its declared maximum.")
        missing = sorted(set(union_ids) - active.keys())
        if missing:
            raise ValueError(
                f"M3 bounded union for {case_id} references unknown merchants: {missing[:3]}"
            )
        labeled = _judgments(
            [active[external_id] for external_id in union_ids],
            tuple(source_case["preferenceTags"]),
            source_case["hardConstraints"],
            hours_by_shop,
        )
        treatment_only = treatment_set - structured_set - control_set
        for judgment in labeled:
            external_id = str(judgment["externalId"])
            origins = []
            if external_id in structured_set:
                origins.append("actual-structured-branch")
            if external_id in control_set:
                origins.append("m2-control-top-k")
            if external_id in treatment_set:
                origins.append("m3-treatment-top-k")
            judgment["judgmentOrigins"] = origins
            if external_id in treatment_only and int(judgment["relevance"]) >= threshold:
                relevant_treatment_only_pairs += 1

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
                "complete-for-frozen-actual-structured-m2-control-m3-treatment-union"
            ),
            "selectionLeakageWarning": M3_SELECTION_LEAKAGE_WARNING,
            "structuredCandidateCount": len(structured_set),
            "structuredCandidateExternalIds": structured,
            "m2ControlReturnedCount": len(control),
            "m2ControlReturnedExternalIds": control,
            "m3TreatmentReturnedCount": len(treatment),
            "m3TreatmentReturnedExternalIds": treatment,
            "m3TreatmentOnlyJudgmentCount": len(treatment_only),
            "m3TreatmentOnlyJudgmentExternalIds": sorted(treatment_only),
            "boundedJudgmentCount": len(labeled),
        }
        cases.append(case)
        structured_pairs += len(structured_set)
        control_pairs += len(control)
        treatment_pairs += len(treatment)
        bounded_pairs += len(labeled)
        treatment_only_pairs += len(treatment_only)

    target_scenarios = {"semantic_alias_composition", "negation_exclusion"}
    if not target_scenarios <= {str(case.get("scenario")) for case in cases}:
        raise ValueError("M3 Dev suite must retain both semantic and negation target subsets.")
    if treatment_only_pairs == 0:
        raise ValueError("M3 treatment did not add a new merchant to the bounded union.")
    if relevant_treatment_only_pairs == 0:
        raise ValueError("M3 treatment added no binary-relevant merchant outside the M2 control pool.")

    full_corpus_merchants = len(active)
    suite = json.loads(json.dumps(source_suite))
    suite.update(
        {
            "schemaVersion": 4,
            "suite": M3_SUITE_NAME,
            "split": "dev",
            "generatorVersion": M3_GENERATOR_VERSION,
            "labelPolicyVersion": LABEL_POLICY_VERSION,
            "adjudicationStatus": "deterministic-bounded-union-not-human-adjudicated",
            "cases": cases,
            "caseCount": len(cases),
            "languageCounts": dict(sorted(Counter(case["language"] for case in cases).items())),
            "scenarioCounts": dict(sorted(Counter(case["scenario"] for case in cases).items())),
            "evaluationDesign": {
                **source_suite["evaluationDesign"],
                "holdout": "m3-dev-only-new-hidden-holdout-required-for-promotion",
                "candidateJudgments": (
                    "bounded-actual-structured-m2-control-and-m3-treatment-output-union"
                ),
                "selectionLeakageWarning": M3_SELECTION_LEAKAGE_WARNING,
                "m1PolicyHoldoutUsed": False,
            },
            "judgmentContract": {
                "policyVersion": M3_JUDGMENT_POLICY_VERSION,
                "scope": "actual-structured-plus-m2-control-top-k-plus-m3-treatment-top-k",
                "unjudgedReturnedPolicy": "fail-closed",
                "selectionLeakageWarning": M3_SELECTION_LEAKAGE_WARNING,
                "sourceSplit": "dev",
                "m1PolicyHoldoutUsed": False,
                "m1PolicyHoldoutForbidden": True,
                "sourceSuite": source_suite["suite"],
                "sourceSuiteSchemaVersion": 3,
                "sourceSuiteCaseSha256": source_suite["caseSha256"],
                "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
                "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
                "candidateUniverseFixture": M3_CANDIDATE_UNIVERSE_FILENAME,
                "candidateUniverseFixtureSha256": candidate_universe["fixtureSha256"],
                "candidateLimit": int(candidate_universe["candidateLimit"]),
                "experimentFingerprint": candidate_universe["experimentFingerprint"],
                "controlConfigFingerprint": candidate_universe["controlConfigFingerprint"],
                "treatmentConfigFingerprint": candidate_universe[
                    "treatmentConfigFingerprint"
                ],
                "controlResultFingerprint": candidate_universe["controlResultFingerprint"],
                "treatmentResultFingerprint": candidate_universe[
                    "treatmentResultFingerprint"
                ],
                "captureIndexManifestFingerprint": candidate_universe[
                    "indexManifestFingerprint"
                ],
                "captureScopedSourceSha256": candidate_universe["scopedSourceSha256"],
                "captureSourceGitSha": candidate_universe["sourceGitSha"],
                "captureRuntimeEnvironment": candidate_universe["runtimeEnvironment"],
                "captureRuntimeEnvironmentFingerprint": candidate_universe[
                    "runtimeEnvironmentFingerprint"
                ],
                "captureQdrantServer": candidate_universe["qdrantServer"],
                "captureQdrantServerFingerprint": candidate_universe[
                    "qdrantServerFingerprint"
                ],
                "embeddingIdentity": candidate_universe["embeddingIdentity"],
                "controlRewriteConfigFingerprint": candidate_universe[
                    "controlRewriteConfigFingerprint"
                ],
                "treatmentRewriteConfigFingerprint": candidate_universe[
                    "treatmentRewriteConfigFingerprint"
                ],
                "treatmentPromptVersion": candidate_universe["treatmentPromptVersion"],
                "treatmentPromptFingerprint": candidate_universe[
                    "treatmentPromptFingerprint"
                ],
                "structuredJudgmentPairs": structured_pairs,
                "m2ControlObservedPairs": control_pairs,
                "m3TreatmentObservedPairs": treatment_pairs,
                "boundedJudgmentPairs": bounded_pairs,
                "m3TreatmentOnlyJudgmentPairs": treatment_only_pairs,
                "binaryRelevantM3TreatmentOnlyPairs": relevant_treatment_only_pairs,
                "fullCorpusMerchantCount": full_corpus_merchants,
                "fullCartesianPairsAvoided": len(cases) * full_corpus_merchants - bounded_pairs,
            },
        }
    )
    suite["caseSha256"] = _fingerprint(cases)
    suite["suiteContractSha256"] = m3_suite_contract_sha256(suite)
    return suite


def write_m3_artifacts(
    output_directory: Path,
    *,
    suite: dict[str, Any],
    candidate_universe: dict[str, Any],
    adversarial_source: Path,
) -> dict[str, Path]:
    """Write the frozen artifacts once, refusing both pre-existing and racing outputs."""

    if not adversarial_source.is_file():
        raise FileNotFoundError("The source suite must have a sibling adversarial fixture.")
    paths = {
        "suite": output_directory / "cases.m3.dev.json",
        "candidateUniverse": output_directory / M3_CANDIDATE_UNIVERSE_FILENAME,
        "adversarialDocuments": output_directory / "adversarial_documents.json",
    }
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("Refusing to overwrite a frozen M3 artifact.")
    output_directory.mkdir(parents=True, exist_ok=True)
    payloads = {
        "suite": (json.dumps(suite, indent=2, ensure_ascii=False) + "\n").encode(),
        "candidateUniverse": (
            json.dumps(candidate_universe, indent=2, ensure_ascii=False) + "\n"
        ).encode(),
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
    arm: str,
) -> dict[str, Any]:
    if int(report.get("schemaVersion") or 0) < 3:
        raise ValueError(f"M3 {arm} capture report must use schemaVersion>=3.")
    suite = report.get("suite") or {}
    source_identity = {
        "suite": source_suite["suite"],
        "split": "dev",
        "caseCount": int(source_suite["caseCount"]),
        "caseSha256": source_suite["caseSha256"],
        "suiteContractSha256": source_suite["suiteContractSha256"],
        "judgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
    }
    if any(suite.get(field) != expected for field, expected in source_identity.items()):
        raise ValueError(f"M3 {arm} capture report does not use the frozen M2 Dev suite.")
    run = report.get("run") or {}
    if run.get("partial") is not False:
        raise ValueError(f"M3 {arm} capture must be complete.")
    _require_exact_integer(run.get("evaluatedCases"), label=f"M3 {arm} evaluatedCases")
    if run["evaluatedCases"] != source_identity["caseCount"]:
        raise ValueError(f"M3 {arm} capture result count differs from its source suite.")
    for counter in _ZERO_CAPTURE_COUNTERS:
        value = run.get(counter, 0)
        _require_exact_integer(value, label=f"M3 {arm} {counter}")
        if value != 0:
            raise ValueError(f"M3 {arm} capture rejects fallback or safety counters.")
    if (report.get("qualityGate") or {}).get("passed") is not True:
        raise ValueError(f"M3 {arm} capture report must pass its per-run gate.")

    results = report.get("results")
    if not isinstance(results, list) or len(results) != source_identity["caseCount"]:
        raise ValueError(f"M3 {arm} capture requires all result rows.")
    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    if [str(result.get("id")) for result in results] != expected_ids:
        raise ValueError(f"M3 {arm} capture result order/IDs differ from M2 Dev.")

    config = run.get("resolvedConfig")
    if not isinstance(config, dict):
        raise ValueError(f"M3 {arm} capture is missing resolvedConfig.")
    if run.get("configFingerprint") != _fingerprint(config):
        raise ValueError(f"M3 {arm} capture config fingerprint is invalid.")
    experiment_fingerprint = m3_experiment_fingerprint(config)
    if run.get("m3ExperimentFingerprint") != experiment_fingerprint:
        raise ValueError(f"M3 {arm} capture experiment fingerprint is invalid.")
    _validate_rewrite_config(run, arm=arm)

    source = run.get("scopedSource")
    if not isinstance(source, dict) or not isinstance(source.get("fileSha256"), dict):
        raise ValueError(f"M3 {arm} capture is missing its scoped source manifest.")
    if source.get("sha256") != _fingerprint(source["fileSha256"]) or source.get("dirty") is not False:
        raise ValueError(f"M3 {arm} capture requires a clean, valid scoped source fingerprint.")
    git = run.get("git")
    if (
        not isinstance(git, dict)
        or not _is_hex_digest(git.get("sha"), lengths={40, 64})
        or git.get("dirty") is not False
    ):
        raise ValueError(f"M3 {arm} capture requires a clean Git source identity.")
    runtime = run.get("runtimeEnvironment")
    if not isinstance(runtime, dict) or not runtime.get("pythonVersion") or not runtime.get(
        "qdrantClientVersion"
    ):
        raise ValueError(f"M3 {arm} capture is missing runtime identities.")
    index = report.get("index")
    if not isinstance(index, dict) or index.get("lifecycleState") != "complete":
        raise ValueError(f"M3 {arm} capture requires a complete reused index.")
    if not _is_sha256(index.get("manifestFingerprint")):
        raise ValueError(f"M3 {arm} capture is missing its index manifest fingerprint.")
    if not isinstance(index.get("qdrantServer"), dict) or not index["qdrantServer"].get("mode"):
        raise ValueError(f"M3 {arm} capture is missing Qdrant Server metadata.")
    embedding_identity = (config.get("embedding") or {}).get("identity")
    if not _is_sha256(embedding_identity):
        raise ValueError(f"M3 {arm} capture is missing its embedding identity.")
    return {**report, "run": run, "index": index, "results": results}


def _validate_capture_pair(control: dict[str, Any], treatment: dict[str, Any]) -> None:
    control_run = control["run"]
    treatment_run = treatment["run"]
    control_config = control_run["resolvedConfig"]
    treatment_config = treatment_run["resolvedConfig"]
    if _normalized_m3_config(control_config) != _normalized_m3_config(treatment_config):
        raise ValueError("M3 capture arms differ outside the isolated rewrite configuration.")
    if control_run["m3ExperimentFingerprint"] != treatment_run["m3ExperimentFingerprint"]:
        raise ValueError("M3 capture arms use different experiment fingerprints.")
    if control_run["scopedSource"] != treatment_run["scopedSource"]:
        raise ValueError("M3 capture arms use different source snapshots.")
    if control_run["git"] != treatment_run["git"]:
        raise ValueError("M3 capture arms use different Git identities.")
    if control_run["runtimeEnvironment"] != treatment_run["runtimeEnvironment"]:
        raise ValueError("M3 capture arms use different runtime environments.")
    if control["index"]["manifestFingerprint"] != treatment["index"]["manifestFingerprint"]:
        raise ValueError("M3 capture arms did not reuse the same frozen index.")
    if control["index"]["qdrantServer"] != treatment["index"]["qdrantServer"]:
        raise ValueError("M3 capture arms use different Qdrant Server identities.")
    if (control_config.get("embedding") or {}).get("identity") != (
        treatment_config.get("embedding") or {}
    ).get("identity"):
        raise ValueError("M3 capture arms use different embedding identities.")


def _validate_rewrite_config(run: dict[str, Any], *, arm: str) -> None:
    config = run["resolvedConfig"]
    features = config.get("features") or {}
    rewrite = config.get("queryRewrite")
    if not isinstance(rewrite, dict):
        raise ValueError(f"M3 {arm} config is missing queryRewrite.")
    expected_fingerprint = rewrite_config_fingerprint(config)
    if run.get("rewriteConfigFingerprint") != expected_fingerprint:
        raise ValueError(f"M3 {arm} rewrite config fingerprint is invalid.")
    if arm == "control":
        if (
            features.get("queryRewriteProvider") != "disabled"
            or features.get("queryRewriteEnabled") is not False
            or rewrite.get("enabled") is not False
            or rewrite.get("provider") != "disabled"
            or rewrite.get("promptFingerprint") is not None
            or run.get("promptFingerprint") is not None
        ):
            raise ValueError("M3 control must explicitly disable query rewrite and its prompt.")
        return
    provider = features.get("queryRewriteProvider")
    prompt_version = rewrite.get("promptVersion")
    prompt_fingerprint = rewrite.get("promptFingerprint")
    if (
        not isinstance(provider, str)
        or provider == "disabled"
        or features.get("queryRewriteEnabled") is not True
        or rewrite.get("enabled") is not True
        or rewrite.get("provider") != provider
        or not isinstance(prompt_version, str)
        or not prompt_version.strip()
        or not _is_sha256(prompt_fingerprint)
        or run.get("promptFingerprint") != prompt_fingerprint
    ):
        raise ValueError("M3 treatment requires an enabled, fingerprinted rewrite prompt/config.")


def _validate_candidate_universe(
    data_directory: Path,
    source_suite: dict[str, Any],
    fixture: dict[str, Any],
) -> None:
    if fixture.get("schemaVersion") != 1 or fixture.get("suite") != M3_CANDIDATE_UNIVERSE_NAME:
        raise ValueError("M3 candidate universe uses an unsupported schema.")
    if fixture.get("fixtureSha256") != m3_candidate_universe_sha256(fixture):
        raise ValueError("M3 candidate-universe fixture SHA is invalid.")
    if fixture.get("selectionLeakageWarning") != M3_SELECTION_LEAKAGE_WARNING:
        raise ValueError("M3 candidate universe must retain its selection-leakage warning.")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))
    expected = {
        "split": "dev",
        "sourceSuite": source_suite["suite"],
        "sourceSuiteSchemaVersion": 3,
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
        "dataVersion": manifest["dataVersion"],
        "datasetSha256": manifest["datasetSha256"],
        "caseCount": int(source_suite["caseCount"]),
    }
    if any(fixture.get(field) != value for field, value in expected.items()):
        raise ValueError("M3 candidate universe differs from its source suite or corpus.")
    candidate_limit = fixture.get("candidateLimit")
    _require_exact_integer(candidate_limit, label="M3 candidateLimit")
    if not 1 <= candidate_limit <= 10:
        raise ValueError("M3 candidateLimit must be between 1 and 10.")
    for field in (
        "experimentFingerprint",
        "controlConfigFingerprint",
        "treatmentConfigFingerprint",
        "controlResultFingerprint",
        "treatmentResultFingerprint",
        "indexManifestFingerprint",
        "scopedSourceSha256",
        "runtimeEnvironmentFingerprint",
        "qdrantServerFingerprint",
        "embeddingIdentity",
        "controlRewriteConfigFingerprint",
        "treatmentRewriteConfigFingerprint",
        "treatmentPromptFingerprint",
    ):
        if not _is_sha256(fixture.get(field)):
            raise ValueError(f"M3 candidate universe has an invalid {field}.")
    if fixture["runtimeEnvironmentFingerprint"] != _fingerprint(fixture["runtimeEnvironment"]):
        raise ValueError("M3 candidate universe runtime fingerprint is invalid.")
    if fixture["qdrantServerFingerprint"] != _fingerprint(fixture["qdrantServer"]):
        raise ValueError("M3 candidate universe Qdrant fingerprint is invalid.")
    if not _is_hex_digest(fixture.get("sourceGitSha"), lengths={40, 64}):
        raise ValueError("M3 candidate universe Git SHA is invalid.")
    if not isinstance(fixture.get("treatmentPromptVersion"), str) or not fixture[
        "treatmentPromptVersion"
    ].strip():
        raise ValueError("M3 candidate universe prompt version is invalid.")

    expected_ids = [str(case["id"]) for case in source_suite["cases"]]
    cases = fixture.get("cases")
    if not isinstance(cases, list) or [str(case.get("id")) for case in cases] != expected_ids:
        raise ValueError("M3 candidate-universe case order/IDs differ from M2 Dev.")
    source_by_id = {str(case["id"]): case for case in source_suite["cases"]}
    counts = {"structured": 0, "control": 0, "treatment": 0}
    for case in cases:
        case_id = str(case["id"])
        structured = _validated_external_ids(
            case.get("structuredBranchExternalIds"),
            label=f"M3 candidate universe {case_id} Structured branch",
            allow_empty=True,
        )
        control = _validated_external_ids(
            case.get("m2ControlReturnedExternalIds"),
            label=f"M3 candidate universe {case_id} M2 control",
            allow_empty=True,
        )
        treatment = _validated_external_ids(
            case.get("m3TreatmentReturnedExternalIds"),
            label=f"M3 candidate universe {case_id} M3 treatment",
            allow_empty=True,
        )
        if len(control) > candidate_limit or len(treatment) > candidate_limit:
            raise ValueError(f"M3 candidate universe {case_id} violates its Top-K bound.")
        source_ids = {
            str(item["externalId"]) for item in source_by_id[case_id].get("judgments") or []
        }
        if not set(structured) <= source_ids:
            raise ValueError(f"M3 candidate universe {case_id} has unknown Structured IDs.")
        counts["structured"] += len(structured)
        counts["control"] += len(control)
        counts["treatment"] += len(treatment)
    expected_counts = {
        "structuredCandidatePairCount": counts["structured"],
        "m2ControlTopKPairCount": counts["control"],
        "m3TreatmentTopKPairCount": counts["treatment"],
    }
    for field, value in expected_counts.items():
        _require_exact_integer(fixture.get(field), label=f"M3 {field}")
        if fixture[field] != value:
            raise ValueError(f"M3 candidate-universe {field} is invalid.")


def _normalized_m3_config(config: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(config))
    value.pop("experimentControlFingerprint", None)
    value.pop("queryRewrite", None)
    features = value.get("features") or {}
    for key in _REWRITE_FEATURE_KEYS:
        features.pop(key, None)
    return value


def _validated_external_ids(value: Any, *, label: str, allow_empty: bool) -> list[str]:
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
        raise ValueError(f"{label} contains an invalid external ID.")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate external IDs.")
    return list(value)


def _require_exact_integer(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _fingerprint(value: Any) -> str:
    return sha256_json(value)


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
        description="Build a bounded, fail-closed schema-v4 M3 Dev judgment suite."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p13-full",
    )
    parser.add_argument("--source-suite", type=Path, default=FROZEN_M2_DEV_SUITE_PATH)
    parser.add_argument("--control-report", type=Path, required=True)
    parser.add_argument("--treatment-report", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    source_suite = json.loads(args.source_suite.read_text(encoding="utf-8"))
    control = json.loads(args.control_report.read_text(encoding="utf-8"))
    treatment = json.loads(args.treatment_report.read_text(encoding="utf-8"))
    universe = capture_m3_candidate_universe(
        source_suite=source_suite,
        control_report=control,
        treatment_report=treatment,
        candidate_limit=args.candidate_limit,
    )
    suite = build_m3_dev_suite(args.dataset.resolve(), source_suite, universe)
    paths = write_m3_artifacts(
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
