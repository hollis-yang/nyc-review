from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.rag_v2.build_m3_cases import (
    M3_JUDGMENT_POLICY_VERSION,
    M3_SELECTION_LEAKAGE_WARNING,
    M3_SUITE_NAME,
    m3_experiment_fingerprint,
    rewrite_config_fingerprint,
)
from evals.rag_v2.contract import sha256_json
from evals.rag_v2.metrics import rounded, summarize_results

POLICY_VERSION = "rag-v2-m3-rewrite-control-treatment-v1"
DEFAULT_GATE = Path(__file__).resolve().parent / "m3_quality_gate.json"
_ZERO_RUN_COUNTERS = (
    "embeddingFallbackCount",
    "retrievalFallbackCount",
    "retrievalIdentityConflictCount",
    "retrievalSafetyRejectionCount",
    "rewriteFallbackCount",
    "rewriteSafetyRejectionCount",
)
_REWRITE_PROVIDER_USAGE_FIELDS = (
    "network_requests",
    "total_tokens",
    "retry_count",
    "failure_count",
    "query_cache_hits",
)
_FLOAT_ABS_TOLERANCE = 1.1e-6


def compare(
    control_path: Path,
    treatment_path: Path,
    *,
    gate_path: Path = DEFAULT_GATE,
) -> dict[str, Any]:
    control = _load_report(control_path)
    treatment = _load_report(treatment_path)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate_sha256 = _file_sha256(gate_path)
    if gate_sha256 != _file_sha256(DEFAULT_GATE):
        raise ValueError("M3 comparison requires the committed m3_quality_gate.json.")
    if gate.get("policyVersion") != POLICY_VERSION:
        raise ValueError("M3 quality gate uses an unsupported policy version.")
    _validate_pair(control, treatment, gate_sha256=gate_sha256)
    budget = _validate_budget_contract(gate, case_count=control["suite"]["caseCount"])

    control_summary = control["summary"]
    treatment_summary = treatment["summary"]
    comparison_gate = gate.get("comparison") or {}
    failures: list[str] = []
    deltas: dict[str, float] = {}
    for path, minimum in (comparison_gate.get("minDeltas") or {}).items():
        control_value = _finite_number_path(control_summary, path)
        treatment_value = _finite_number_path(treatment_summary, path)
        delta = treatment_value - control_value
        deltas[path] = delta
        if delta < _finite_gate_number(minimum, path=path):
            failures.append(f"{path} delta={delta:.6f} is below {minimum}")
    for path, maximum_drop in (comparison_gate.get("maxDrops") or {}).items():
        control_value = _finite_number_path(control_summary, path)
        treatment_value = _finite_number_path(treatment_summary, path)
        drop = control_value - treatment_value
        deltas.setdefault(path, -drop)
        if drop > _finite_gate_number(maximum_drop, path=path):
            failures.append(f"{path} dropped {drop:.6f}; maximum is {maximum_drop}")
    for path, minimum in (comparison_gate.get("treatmentMinimums") or {}).items():
        value = _finite_number_path(treatment_summary, path)
        if value < _finite_gate_number(minimum, path=path):
            failures.append(f"treatment {path}={value:.6f} is below {minimum}")
    for path, maximum in (comparison_gate.get("treatmentMaximums") or {}).items():
        value = _finite_number_path(treatment_summary, path)
        if value > _finite_gate_number(maximum, path=path):
            failures.append(f"treatment {path}={value:.6f} exceeds {maximum}")

    ratios: dict[str, float] = {}
    for path, maximum_ratio in (comparison_gate.get("maxRatios") or {}).items():
        control_value = _finite_number_path(control_summary, path)
        treatment_value = _finite_number_path(treatment_summary, path)
        if control_value <= 0:
            raise ValueError(f"M3 ratio baseline {path!r} must be positive.")
        ratio = treatment_value / control_value
        if not math.isfinite(ratio):
            raise ValueError(f"M3 ratio {path!r} is non-finite.")
        ratios[path] = ratio
        if ratio > _finite_gate_number(maximum_ratio, path=path):
            failures.append(f"{path} ratio={ratio:.6f} exceeds {maximum_ratio}")

    request_deltas: dict[str, int] = {}
    for path, maximum_increase in (comparison_gate.get("maxIncreases") or {}).items():
        control_value = _integer_path(control_summary, path)
        treatment_value = _integer_path(treatment_summary, path)
        maximum = _exact_gate_integer(maximum_increase, path=path)
        increase = treatment_value - control_value
        request_deltas[path] = increase
        if increase > maximum:
            failures.append(f"{path} increased by {increase}; maximum is {maximum}")

    costs = {
        "control": control["run"]["rewriteProviderCost"],
        "treatment": treatment["run"]["rewriteProviderCost"],
    }
    control_cost = costs["control"]
    treatment_cost = costs["treatment"]
    maximum_rewrite_cost = budget["maxRewriteEstimatedCostUsd"]
    if control_cost["estimatedCostUsd"] != 0.0:
        raise ValueError("M3 rewrite-disabled control must report zero rewrite provider cost.")
    if treatment_cost["hardCostCapUsd"] > maximum_rewrite_cost:
        failures.append(
            "treatment rewrite hard cost cap="
            f"{treatment_cost['hardCostCapUsd']:.6f} exceeds {maximum_rewrite_cost}"
        )
    if treatment_cost["estimatedCostUsd"] > maximum_rewrite_cost:
        failures.append(
            "treatment rewrite estimated cost="
            f"{treatment_cost['estimatedCostUsd']:.6f} exceeds {maximum_rewrite_cost}"
        )
    if treatment_cost["estimatedCostUsd"] > treatment_cost["hardCostCapUsd"]:
        failures.append(
            "treatment rewrite estimated cost exceeds its report-bound hard cost cap"
        )

    control_by_id = {str(item["id"]): item for item in control["results"]}
    case_deltas = []
    for treatment_case in treatment["results"]:
        case_id = str(treatment_case["id"])
        control_case = control_by_id[case_id]
        case_deltas.append(
            {
                "id": case_id,
                "scenario": treatment_case["scenario"],
                "recallAt10": (
                    float(treatment_case["metrics"]["recallAt10"])
                    - float(control_case["metrics"]["recallAt10"])
                ),
                "ndcgAt10": (
                    float(treatment_case["metrics"]["ndcgAt10"])
                    - float(control_case["metrics"]["ndcgAt10"])
                ),
            }
        )

    output = {
        "schemaVersion": 1,
        "policyVersion": POLICY_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "passed": not failures,
        "failures": failures,
        "suite": {
            key: control["suite"][key]
            for key in (
                "suite",
                "split",
                "caseCount",
                "caseSha256",
                "suiteContractSha256",
                "judgmentContractSha256",
            )
        },
        "manifest": {
            "controlReport": {
                "filename": control_path.name,
                "sha256": _file_sha256(control_path),
            },
            "treatmentReport": {
                "filename": treatment_path.name,
                "sha256": _file_sha256(treatment_path),
            },
            "qualityGate": {
                "filename": gate_path.name,
                "sha256": gate_sha256,
            },
            "experimentFingerprint": control["run"]["m3ExperimentFingerprint"],
            "controlConfigFingerprint": control["run"]["configFingerprint"],
            "treatmentConfigFingerprint": treatment["run"]["configFingerprint"],
            "controlRewriteConfigFingerprint": control["run"][
                "rewriteConfigFingerprint"
            ],
            "treatmentRewriteConfigFingerprint": treatment["run"][
                "rewriteConfigFingerprint"
            ],
            "treatmentPromptFingerprint": treatment["run"]["promptFingerprint"],
            "indexManifestFingerprint": control["index"]["manifestFingerprint"],
        },
        "deltas": deltas,
        "ratios": ratios,
        "requestDeltas": request_deltas,
        "costs": costs,
        "control": {"rewriteEnabled": False, "summary": control_summary},
        "treatment": {"rewriteEnabled": True, "summary": treatment_summary},
        "caseDeltas": case_deltas,
        "thresholds": gate,
    }
    return rounded(output)


def write_comparison(path: Path, result: dict[str, Any]) -> None:
    """Persist one comparison without ever replacing prior formal evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    suite = report.get("suite") or {}
    run = report.get("run") or {}
    results = report.get("results")
    if int(report.get("schemaVersion") or 0) != 4 or int(suite.get("schemaVersion") or 0) != 4:
        raise ValueError(f"M3 report must use schemaVersion=4: {path}")
    if (
        suite.get("suite") != M3_SUITE_NAME
        or suite.get("split") != "dev"
        or not suite.get("judgmentContractSha256")
    ):
        raise ValueError("M3 comparison accepts only the frozen schema-v4 Dev contract.")
    case_count = suite.get("caseCount")
    _require_exact_integer(case_count, label="M3 suite caseCount")
    if run.get("partial") is not False:
        raise ValueError("M3 comparison requires complete reports.")
    _require_exact_integer(run.get("evaluatedCases"), label="M3 evaluatedCases")
    if run["evaluatedCases"] != case_count:
        raise ValueError("M3 evaluatedCases differs from the suite caseCount.")
    if not isinstance(results, list) or len(results) != case_count:
        raise ValueError("M3 report result count does not match its suite.")
    result_ids = [str(result.get("id")) for result in results]
    if any(not value for value in result_ids) or len(result_ids) != len(set(result_ids)):
        raise ValueError("M3 report result IDs are missing or duplicated.")
    if (report.get("qualityGate") or {}).get("passed") is not True:
        raise ValueError("Each M3 arm must pass its per-run quality gate.")
    for counter in _ZERO_RUN_COUNTERS:
        value = run.get(counter, 0)
        _require_exact_integer(value, label=f"M3 {counter}")
        if value != 0:
            raise ValueError("M3 comparison rejects rewrite, embedding, or retrieval fallback/safety events.")
    if any(
        candidate.get("judged") is not True
        for result in results
        for candidate in result.get("orderedCandidates") or []
    ):
        raise ValueError("M3 report contains an unjudged returned merchant.")
    recomputed = rounded(_summarize_m3_results(results))
    if not _summaries_match(recomputed, report.get("summary")):
        raise ValueError("M3 report summary does not match recomputation from result rows.")
    _validate_rewrite_cost_report(
        run,
        scored_cost=recomputed["costUsd"]["queryRewrite"],
    )
    return report


def _summarize_m3_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    for result in results:
        requests = result.get("requests")
        if not isinstance(requests, dict):
            raise ValueError(f"M3 result {result.get('id')} is missing request counters.")
        for field in ("rewriteRequests", "rerankerRequests"):
            _require_exact_integer(requests.get(field, 0), label=f"M3 result {field}")
        rewrite_usage = requests.get("rewriteProviderUsage") or {}
        if not isinstance(rewrite_usage, dict):
            raise ValueError("M3 rewriteProviderUsage must be an object.")
        for field in _REWRITE_PROVIDER_USAGE_FIELDS:
            _require_exact_integer(
                rewrite_usage.get(field, 0),
                label=f"M3 rewriteProviderUsage.{field}",
            )
        _finite_nonnegative_float(
            rewrite_usage.get("estimated_cost_usd"),
            label="M3 rewriteProviderUsage.estimated_cost_usd",
        )

    summary = summarize_results(results)
    request_counts = summary["requestCounts"]
    request_counts.update(
        {
            "rewriteProviderNetworkRequests": sum(
                int((result["requests"].get("rewriteProviderUsage") or {}).get("network_requests", 0))
                for result in results
            ),
            "rewriteProviderTokens": sum(
                int((result["requests"].get("rewriteProviderUsage") or {}).get("total_tokens", 0))
                for result in results
            ),
            "rewriteProviderRetries": sum(
                int((result["requests"].get("rewriteProviderUsage") or {}).get("retry_count", 0))
                for result in results
            ),
            "rewriteProviderFailures": sum(
                int((result["requests"].get("rewriteProviderUsage") or {}).get("failure_count", 0))
                for result in results
            ),
            "rewriteCacheHits": sum(
                int((result["requests"].get("rewriteProviderUsage") or {}).get("query_cache_hits", 0))
                for result in results
            ),
        }
    )
    summary["costUsd"] = {
        "queryRewrite": sum(
            float(
                (result["requests"].get("rewriteProviderUsage") or {})[
                    "estimated_cost_usd"
                ]
            )
            for result in results
        )
    }
    return summary


def _summaries_match(expected: Any, observed: Any) -> bool:
    """Keep structure and integer counters exact; tolerate only six-decimal float drift."""

    if isinstance(expected, dict):
        return isinstance(observed, dict) and expected.keys() == observed.keys() and all(
            _summaries_match(value, observed[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and len(expected) == len(observed) and all(
            _summaries_match(left, right) for left, right in zip(expected, observed, strict=True)
        )
    if isinstance(expected, bool):
        return isinstance(observed, bool) and expected == observed
    if isinstance(expected, int):
        return isinstance(observed, int) and not isinstance(observed, bool) and expected == observed
    if isinstance(expected, float):
        return (
            isinstance(observed, float)
            and math.isfinite(expected)
            and math.isfinite(observed)
            and math.isclose(
                expected,
                observed,
                rel_tol=0.0,
                abs_tol=_FLOAT_ABS_TOLERANCE,
            )
        )
    return expected == observed


def _validate_pair(
    control: dict[str, Any],
    treatment: dict[str, Any],
    *,
    gate_sha256: str,
) -> None:
    suite_fields = (
        "schemaVersion",
        "suite",
        "split",
        "caseCount",
        "caseSha256",
        "suiteContractSha256",
        "judgmentContractSha256",
    )
    if any(control["suite"].get(field) != treatment["suite"].get(field) for field in suite_fields):
        raise ValueError("M3 control/treatment reports use different frozen suites.")
    if control["suite"].get("split") != "dev":
        raise ValueError("M3 comparison permanently rejects the consumed M1 Test holdout.")
    if [str(item["id"]) for item in control["results"]] != [
        str(item["id"]) for item in treatment["results"]
    ]:
        raise ValueError("M3 control/treatment result order or IDs differ.")
    for arm, report in (("control", control), ("treatment", treatment)):
        _validate_report_bindings(report, arm=arm)
        observed_gate = ((report.get("run") or {}).get("policyArtifacts") or {}).get(
            "qualityGateSha256"
        )
        if observed_gate != gate_sha256:
            raise ValueError("M3 report is not bound to the committed quality gate.")

    control_run = control["run"]
    treatment_run = treatment["run"]
    control_config = control_run["resolvedConfig"]
    treatment_config = treatment_run["resolvedConfig"]
    if m3_experiment_fingerprint(control_config) != m3_experiment_fingerprint(treatment_config):
        raise ValueError("M3 arms differ outside the isolated rewrite switch/configuration.")
    if control_run["m3ExperimentFingerprint"] != treatment_run["m3ExperimentFingerprint"]:
        raise ValueError("M3 arms use different experiment fingerprints.")
    if control_run["scopedSource"] != treatment_run["scopedSource"]:
        raise ValueError("M3 arms use different Eval/retrieval/rewrite source snapshots.")
    if control_run["git"] != treatment_run["git"]:
        raise ValueError("M3 arms use different Git identities.")
    if control_run["runtimeEnvironment"] != treatment_run["runtimeEnvironment"]:
        raise ValueError("M3 arms use different runtime environments.")
    if control["index"].get("qdrantServer") != treatment["index"].get("qdrantServer"):
        raise ValueError("M3 arms use different Qdrant Server metadata.")
    if control["index"].get("manifestFingerprint") != treatment["index"].get(
        "manifestFingerprint"
    ):
        raise ValueError("M3 arms did not reuse the exact same frozen index manifest.")
    if (
        control["index"].get("lifecycleState") != "complete"
        or treatment["index"].get("lifecycleState") != "complete"
    ):
        raise ValueError("M3 comparison requires a complete, ready index in both arms.")


def _validate_report_bindings(report: dict[str, Any], *, arm: str) -> None:
    suite = report["suite"]
    run = report["run"]
    config = run.get("resolvedConfig")
    if not isinstance(config, dict):
        raise ValueError("M3 report is missing its resolved configuration.")
    config_fingerprint = _fingerprint(config)
    if run.get("configFingerprint") != config_fingerprint:
        raise ValueError("M3 report config fingerprint is invalid.")
    experiment_fingerprint = m3_experiment_fingerprint(config)
    if run.get("m3ExperimentFingerprint") != experiment_fingerprint:
        raise ValueError("M3 report experiment fingerprint is invalid.")
    _validate_report_rewrite_identity(run, arm=arm)

    source = run.get("scopedSource")
    if not isinstance(source, dict) or not isinstance(source.get("fileSha256"), dict):
        raise ValueError("M3 report is missing its scoped source manifest.")
    if source.get("sha256") != _fingerprint(source["fileSha256"]) or source.get("dirty") is not False:
        raise ValueError("M3 report scoped source fingerprint is invalid or dirty.")
    git = run.get("git")
    if not isinstance(git, dict) or git.get("dirty") is not False or not git.get("sha"):
        raise ValueError("M3 report requires a clean Git identity.")
    runtime = run.get("runtimeEnvironment")
    if not isinstance(runtime, dict) or not runtime.get("qdrantClientVersion"):
        raise ValueError("M3 report is missing its runtime identity.")
    qdrant_server = report["index"].get("qdrantServer")
    if not isinstance(qdrant_server, dict) or not qdrant_server.get("mode"):
        raise ValueError("M3 report is missing Qdrant Server metadata.")

    contract = suite.get("judgmentContract")
    if not isinstance(contract, dict) or contract.get("policyVersion") != M3_JUDGMENT_POLICY_VERSION:
        raise ValueError("M3 report is missing its schema-v4 bounded judgment contract.")
    judgment_sha256 = _fingerprint(contract)
    if suite.get("judgmentContractSha256") != judgment_sha256:
        raise ValueError("M3 report judgment contract SHA is invalid.")
    if (
        contract.get("sourceSplit") != "dev"
        or contract.get("m1PolicyHoldoutUsed") is not False
        or contract.get("m1PolicyHoldoutForbidden") is not True
        or contract.get("unjudgedReturnedPolicy") != "fail-closed"
        or contract.get("selectionLeakageWarning") != M3_SELECTION_LEAKAGE_WARNING
    ):
        raise ValueError("M3 report violates its Dev-only fail-closed judgment policy.")
    expected_arm_config = contract[f"{arm}ConfigFingerprint"]
    if config_fingerprint != expected_arm_config:
        raise ValueError(f"M3 {arm} config differs from candidate capture.")
    expected_rewrite = contract[f"{arm}RewriteConfigFingerprint"]
    if run.get("rewriteConfigFingerprint") != expected_rewrite:
        raise ValueError(f"M3 {arm} rewrite fingerprint differs from candidate capture.")
    expected_capture = {
        "m3ExperimentFingerprint": contract["experimentFingerprint"],
        "scopedSourceSha256": contract["captureScopedSourceSha256"],
        "sourceGitSha": contract["captureSourceGitSha"],
        "runtimeEnvironment": contract["captureRuntimeEnvironment"],
        "runtimeEnvironmentFingerprint": contract["captureRuntimeEnvironmentFingerprint"],
        "qdrantServer": contract["captureQdrantServer"],
        "qdrantServerFingerprint": contract["captureQdrantServerFingerprint"],
        "indexManifestFingerprint": contract["captureIndexManifestFingerprint"],
        "embeddingIdentity": contract["embeddingIdentity"],
    }
    observed_capture = {
        "m3ExperimentFingerprint": run["m3ExperimentFingerprint"],
        "scopedSourceSha256": source["sha256"],
        "sourceGitSha": git["sha"],
        "runtimeEnvironment": runtime,
        "runtimeEnvironmentFingerprint": _fingerprint(runtime),
        "qdrantServer": qdrant_server,
        "qdrantServerFingerprint": _fingerprint(qdrant_server),
        "indexManifestFingerprint": report["index"]["manifestFingerprint"],
        "embeddingIdentity": (config.get("embedding") or {}).get("identity"),
    }
    if observed_capture != expected_capture:
        raise ValueError("M3 report source/runtime/index identity differs from candidate capture.")
    if arm == "treatment" and (
        run.get("promptFingerprint") != contract["treatmentPromptFingerprint"]
        or config["queryRewrite"].get("promptVersion") != contract["treatmentPromptVersion"]
    ):
        raise ValueError("M3 treatment prompt differs from candidate capture.")

    manifest = report.get("evaluationManifest")
    if not isinstance(manifest, dict):
        raise ValueError("M3 report is missing its evaluation manifest.")
    features = config.get("features") or {}
    expected_manifest = {
        "suiteSchemaVersion": 4,
        "suiteContractSha256": suite["suiteContractSha256"],
        "caseSha256": suite["caseSha256"],
        "judgmentContractSha256": judgment_sha256,
        "candidateUniverseFixtureSha256": contract["candidateUniverseFixtureSha256"],
        "configFingerprint": config_fingerprint,
        "m3ExperimentFingerprint": experiment_fingerprint,
        "scopedSourceSha256": source["sha256"],
        "sourceGitSha": git["sha"],
        "runtimeEnvironmentFingerprint": _fingerprint(runtime),
        "indexManifestFingerprint": report["index"]["manifestFingerprint"],
        "qdrantServerFingerprint": _fingerprint(qdrant_server),
        "embeddingIdentity": (config.get("embedding") or {}).get("identity"),
        "retrievalMode": (config.get("retrieval") or {}).get("mode"),
        "globalRetrievalEnabled": features.get("globalRetrievalEnabled"),
        "queryRewriteProvider": features.get("queryRewriteProvider"),
        "queryRewriteEnabled": features.get("queryRewriteEnabled"),
        "promptFingerprint": run.get("promptFingerprint"),
        "rewriteConfigFingerprint": run.get("rewriteConfigFingerprint"),
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise ValueError(f"M3 evaluation manifest {field} does not match its report.")


def _validate_report_rewrite_identity(run: dict[str, Any], *, arm: str) -> None:
    config = run["resolvedConfig"]
    features = config.get("features") or {}
    retrieval = config.get("retrieval") or {}
    rewrite = config.get("queryRewrite")
    if (
        retrieval.get("mode") != "global-hybrid"
        or features.get("globalRetrievalEnabled") is not True
        or not isinstance(rewrite, dict)
    ):
        raise ValueError("M3 requires the same enabled global-hybrid retrieval in both arms.")
    expected_rewrite_fingerprint = rewrite_config_fingerprint(config)
    if run.get("rewriteConfigFingerprint") != expected_rewrite_fingerprint:
        raise ValueError("M3 rewrite config fingerprint is invalid.")
    if arm == "control":
        if (
            features.get("queryRewriteProvider") != "disabled"
            or features.get("queryRewriteEnabled") is not False
            or rewrite.get("enabled") is not False
            or rewrite.get("provider") != "disabled"
            or rewrite.get("promptFingerprint") is not None
            or run.get("promptFingerprint") is not None
        ):
            raise ValueError("M3 control must explicitly disable query rewrite.")
        return
    provider = features.get("queryRewriteProvider")
    if (
        not isinstance(provider, str)
        or provider == "disabled"
        or features.get("queryRewriteEnabled") is not True
        or rewrite.get("enabled") is not True
        or rewrite.get("provider") != provider
        or not isinstance(rewrite.get("promptVersion"), str)
        or not rewrite["promptVersion"].strip()
        or not _is_sha256(rewrite.get("promptFingerprint"))
        or run.get("promptFingerprint") != rewrite.get("promptFingerprint")
    ):
        raise ValueError("M3 treatment must enable a fingerprinted rewrite prompt/config.")


def _finite_number_path(value: dict[str, Any], path: str) -> float:
    observed = _path(value, path)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise ValueError(f"M3 gate path {path!r} is not numeric.")
    result = float(observed)
    if not math.isfinite(result):
        raise ValueError(f"M3 gate path {path!r} is non-finite.")
    return result


def _integer_path(value: dict[str, Any], path: str) -> int:
    observed = _path(value, path)
    _require_exact_integer(observed, label=f"M3 gate path {path}")
    return observed


def _path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise ValueError(f"M3 gate path {path!r} is missing.")
        current = current[segment]
    if current is None:
        raise ValueError(f"M3 gate path {path!r} is not measurable.")
    return current


def _finite_gate_number(value: Any, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"M3 gate threshold {path!r} is not numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"M3 gate threshold {path!r} is non-finite.")
    return result


def _validate_budget_contract(gate: dict[str, Any], *, case_count: int) -> dict[str, Any]:
    budget = gate.get("budgetContract")
    if not isinstance(budget, dict):
        raise ValueError("M3 quality gate is missing its bounded rewrite budget contract.")
    integer_fields = (
        "maximumCases",
        "maxTreatmentQueryVariantsPerCase",
        "maxAdditionalEmbeddingQueriesPerCase",
        "maxQueryVariantCharacters",
        "maxAdditionalEmbeddingNetworkRequests",
        "maxAdditionalEmbeddingTokens",
        "maxRewriteProviderNetworkRequests",
        "maxRewriteProviderTokens",
    )
    for field in integer_fields:
        _require_exact_integer(budget.get(field), label=f"M3 budgetContract.{field}")
    if case_count > budget["maximumCases"]:
        raise ValueError("M3 suite exceeds the frozen rewrite budget case count.")
    if (
        budget["maxTreatmentQueryVariantsPerCase"] != 5
        or budget["maxAdditionalEmbeddingQueriesPerCase"] != 4
        or budget["maxAdditionalEmbeddingNetworkRequests"]
        != budget["maximumCases"] * budget["maxAdditionalEmbeddingQueriesPerCase"]
        or budget["maxAdditionalEmbeddingTokens"]
        != (
            budget["maximumCases"]
            * budget["maxAdditionalEmbeddingQueriesPerCase"]
            * budget["maxQueryVariantCharacters"]
        )
    ):
        raise ValueError("M3 quality gate has an inconsistent bounded-query budget.")
    _finite_nonnegative_float(
        budget.get("maxRewriteEstimatedCostUsd"),
        label="M3 budgetContract.maxRewriteEstimatedCostUsd",
    )
    return budget


def _validate_rewrite_cost_report(run: dict[str, Any], *, scored_cost: float) -> None:
    cost = run.get("rewriteProviderCost")
    expected_fields = {
        "scoredEstimatedCostUsd",
        "warmupEstimatedCostUsd",
        "estimatedCostUsd",
        "hardCostCapUsd",
    }
    if not isinstance(cost, dict) or cost.keys() != expected_fields:
        raise ValueError("M3 report is missing its exact rewrite provider cost contract.")
    for field in expected_fields:
        _finite_nonnegative_float(cost[field], label=f"M3 rewriteProviderCost.{field}")
    if not math.isclose(
        cost["scoredEstimatedCostUsd"],
        scored_cost,
        rel_tol=0.0,
        abs_tol=_FLOAT_ABS_TOLERANCE,
    ):
        raise ValueError("M3 scored rewrite cost does not match result-row usage.")
    if not math.isclose(
        cost["estimatedCostUsd"],
        cost["scoredEstimatedCostUsd"] + cost["warmupEstimatedCostUsd"],
        rel_tol=0.0,
        abs_tol=_FLOAT_ABS_TOLERANCE,
    ):
        raise ValueError("M3 total rewrite cost does not equal scored plus warmup cost.")


def _finite_nonnegative_float(value: Any, *, label: str) -> float:
    if not isinstance(value, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite non-negative float.")
    return value


def _exact_gate_integer(value: Any, *, path: str) -> int:
    _require_exact_integer(value, label=f"M3 gate threshold {path}")
    return value


def _require_exact_integer(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _fingerprint(value: Any) -> str:
    return sha256_json(value)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare frozen M3 rewrite-disabled control and rewrite-enabled treatment."
    )
    parser.add_argument("control", type=Path)
    parser.add_argument("treatment", type=Path)
    parser.add_argument("--quality-gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.control, args.treatment, gate_path=args.quality_gate)
    write_comparison(args.output, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
