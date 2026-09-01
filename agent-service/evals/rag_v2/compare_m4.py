from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.rag_v2.build_m4_cases import (
    M4_JUDGMENT_POLICY_VERSION,
    M4_SELECTION_LEAKAGE_WARNING,
    M4_SUITE_NAME,
    extract_pre_rerank_contract,
    m4_experiment_fingerprint,
    reranker_config_fingerprint,
)
from evals.rag_v2.contract import sha256_json
from evals.rag_v2.metrics import rounded, summarize_results

POLICY_VERSION = "rag-v2-m4-reranker-control-treatment-v1"
DEFAULT_GATE = Path(__file__).resolve().parent / "m4_quality_gate.json"
_FLOAT_ABS_TOLERANCE = 1.1e-6
_RERANKER_PROVIDER_USAGE_FIELDS = (
    "network_requests",
    "total_tokens",
    "retry_count",
    "failure_count",
    "cache_hits",
)
_ZERO_RUN_COUNTERS = (
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


def compare(
    control_path: Path,
    treatment_path: Path,
    *,
    gate_path: Path = DEFAULT_GATE,
) -> dict[str, Any]:
    control = _load_report(control_path, arm="control")
    treatment = _load_report(treatment_path, arm="treatment")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate_sha256 = _file_sha256(gate_path)
    if gate_sha256 != _file_sha256(DEFAULT_GATE):
        raise ValueError("M4 comparison requires the committed m4_quality_gate.json.")
    if gate.get("policyVersion") != POLICY_VERSION:
        raise ValueError("M4 quality gate uses an unsupported policy version.")
    budget = _validate_budget_contract(gate, case_count=control["suite"]["caseCount"])
    _validate_pair(control, treatment, gate_sha256=gate_sha256)

    control_summary = control["summary"]
    treatment_summary = treatment["summary"]
    comparison_gate = gate.get("comparison") or {}
    failures: list[str] = []
    deltas: dict[str, float] = {}
    for path, minimum in (comparison_gate.get("minDeltas") or {}).items():
        delta = _finite_number_path(treatment_summary, path) - _finite_number_path(
            control_summary, path
        )
        deltas[path] = delta
        if delta < _finite_gate_number(minimum, path=path):
            failures.append(f"{path} delta={delta:.6f} is below {minimum}")
    for path, maximum_drop in (comparison_gate.get("maxDrops") or {}).items():
        drop = _finite_number_path(control_summary, path) - _finite_number_path(
            treatment_summary, path
        )
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

    request_deltas: dict[str, int] = {}
    for path, maximum_increase in (comparison_gate.get("maxIncreases") or {}).items():
        control_value = _integer_path(control_summary, path)
        treatment_value = _integer_path(treatment_summary, path)
        maximum = _exact_gate_integer(maximum_increase, path=path)
        increase = treatment_value - control_value
        request_deltas[path] = increase
        if increase > maximum:
            failures.append(f"{path} increased by {increase}; maximum is {maximum}")

    bootstrap_config = gate.get("pairedBootstrap") or {}
    metric = str(bootstrap_config.get("metric") or "")
    if metric != "ndcgAt5":
        raise ValueError("M4 paired bootstrap must use the frozen ndcgAt5 metric.")
    paired_deltas = [
        float(treatment_row["metrics"][metric]) - float(control_row["metrics"][metric])
        for control_row, treatment_row in zip(
            control["results"], treatment["results"], strict=True
        )
    ]
    bootstrap = paired_bootstrap_mean_ci(
        paired_deltas,
        confidence=_finite_probability(
            bootstrap_config.get("confidence"), label="M4 bootstrap confidence"
        ),
        resamples=_positive_integer(
            bootstrap_config.get("resamples"), label="M4 bootstrap resamples"
        ),
        seed=_nonnegative_integer(
            bootstrap_config.get("seed"), label="M4 bootstrap seed"
        ),
    )
    minimum_delta = _finite_gate_number(
        bootstrap_config.get("minimumObservedDelta"), path="pairedBootstrap.minimumObservedDelta"
    )
    minimum_lower = _finite_gate_number(
        bootstrap_config.get("minimumLowerBound"), path="pairedBootstrap.minimumLowerBound"
    )
    if bootstrap["observedMeanDelta"] < minimum_delta:
        failures.append(
            "paired bootstrap observed nDCG@5 delta="
            f"{bootstrap['observedMeanDelta']:.6f} is below {minimum_delta}"
        )
    if bootstrap["lower"] < minimum_lower:
        failures.append(
            "paired bootstrap nDCG@5 CI lower="
            f"{bootstrap['lower']:.6f} is below {minimum_lower}"
        )

    costs = {
        "control": control["run"]["rerankerProviderCost"],
        "treatment": treatment["run"]["rerankerProviderCost"],
    }
    max_cost = float(budget["maxRerankerEstimatedCostUsd"])
    if costs["control"]["estimatedCostUsd"] != 0.0:
        raise ValueError("M4 heuristic control must report zero reranker provider cost.")
    if costs["treatment"]["hardCostCapUsd"] > max_cost:
        failures.append(
            "treatment reranker hard cost cap="
            f"{costs['treatment']['hardCostCapUsd']:.6f} exceeds {max_cost}"
        )
    if costs["treatment"]["estimatedCostUsd"] > max_cost:
        failures.append(
            "treatment reranker estimated cost="
            f"{costs['treatment']['estimatedCostUsd']:.6f} exceeds {max_cost}"
        )
    if costs["treatment"]["estimatedCostUsd"] > costs["treatment"]["hardCostCapUsd"]:
        failures.append("treatment reranker estimated cost exceeds its report hard cap")

    latency_observation = _latency_observation(control_summary, treatment_summary)
    control_by_id = {str(item["id"]): item for item in control["results"]}
    case_deltas = []
    for treatment_case in treatment["results"]:
        case_id = str(treatment_case["id"])
        control_case = control_by_id[case_id]
        case_deltas.append(
            {
                "id": case_id,
                "scenario": treatment_case["scenario"],
                "ndcgAt5": float(treatment_case["metrics"]["ndcgAt5"])
                - float(control_case["metrics"]["ndcgAt5"]),
                "recallAt10": float(treatment_case["metrics"]["recallAt10"])
                - float(control_case["metrics"]["recallAt10"]),
            }
        )

    output = {
        "schemaVersion": 1,
        "policyVersion": POLICY_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "passed": not failures,
        "failures": failures,
        "promotionStatus": (
            "quality-accepted-under-latency-waiver"
            if not failures
            else "quality-gate-failed"
        ),
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
            "qualityGate": {"filename": gate_path.name, "sha256": gate_sha256},
            "experimentFingerprint": control["run"]["m4ExperimentFingerprint"],
            "controlConfigFingerprint": control["run"]["configFingerprint"],
            "treatmentConfigFingerprint": treatment["run"]["configFingerprint"],
            "controlRerankerConfigFingerprint": control["run"][
                "rerankerConfigFingerprint"
            ],
            "treatmentRerankerConfigFingerprint": treatment["run"][
                "rerankerConfigFingerprint"
            ],
            "candidatePoolContractSha256": control["suite"]["judgmentContract"][
                "candidatePoolContractSha256"
            ],
            "indexManifestFingerprint": control["index"]["manifestFingerprint"],
        },
        "deltas": deltas,
        "pairedBootstrap": bootstrap,
        "requestDeltas": request_deltas,
        "costs": costs,
        "latencyObservation": latency_observation,
        "control": {"reranker": "heuristic-multi-signal", "summary": control_summary},
        "treatment": {
            "reranker": _reranker_provider(treatment["run"]["resolvedConfig"]),
            "summary": treatment_summary,
        },
        "caseDeltas": case_deltas,
        "thresholds": gate,
    }
    return rounded(output)


def paired_bootstrap_mean_ci(
    deltas: list[float],
    *,
    confidence: float,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    if not deltas:
        raise ValueError("M4 paired bootstrap requires at least one paired case.")
    if any(not math.isfinite(float(value)) for value in deltas):
        raise ValueError("M4 paired bootstrap received a non-finite delta.")
    randomizer = random.Random(seed)
    count = len(deltas)
    means = sorted(
        sum(deltas[randomizer.randrange(count)] for _ in range(count)) / count
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    return {
        "metric": "ndcgAt5",
        "observedMeanDelta": sum(deltas) / count,
        "lower": _linear_quantile(means, alpha),
        "upper": _linear_quantile(means, 1.0 - alpha),
        "confidence": confidence,
        "resamples": resamples,
        "seed": seed,
        "caseCount": count,
    }


def write_comparison(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)


def _load_report(path: Path, *, arm: str) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    suite = report.get("suite") or {}
    run = report.get("run") or {}
    results = report.get("results")
    if int(report.get("schemaVersion") or 0) != 5 or int(
        suite.get("schemaVersion") or 0
    ) != 5:
        raise ValueError(f"M4 report must use schemaVersion=5: {path}")
    if (
        suite.get("suite") != M4_SUITE_NAME
        or suite.get("split") != "dev"
        or not suite.get("judgmentContractSha256")
    ):
        raise ValueError("M4 comparison accepts only the frozen schema-v5 Dev contract.")
    case_count = suite.get("caseCount")
    _require_exact_integer(case_count, label="M4 suite caseCount")
    if run.get("partial") is not False:
        raise ValueError("M4 comparison requires complete reports.")
    _require_exact_integer(run.get("evaluatedCases"), label="M4 evaluatedCases")
    if run["evaluatedCases"] != case_count:
        raise ValueError("M4 evaluatedCases differs from suite caseCount.")
    if not isinstance(results, list) or len(results) != case_count:
        raise ValueError("M4 report result count does not match its suite.")
    result_ids = [str(result.get("id")) for result in results]
    if any(not value for value in result_ids) or len(result_ids) != len(set(result_ids)):
        raise ValueError("M4 report result IDs are missing or duplicated.")
    if (report.get("qualityGate") or {}).get("passed") is not True:
        raise ValueError("Each M4 arm must pass its per-run integrity gate.")
    for counter in _ZERO_RUN_COUNTERS:
        value = run.get(counter, 0)
        _require_exact_integer(value, label=f"M4 {counter}")
        if value:
            raise ValueError("M4 formal reports reject fallback, retry, failure, or safety events.")
    if any(
        candidate.get("judged") is not True
        for result in results
        for candidate in result.get("orderedCandidates") or []
    ):
        raise ValueError("M4 report contains an unjudged returned merchant.")

    _validate_report_bindings(report, arm=arm)
    _validate_result_pool_bindings(report, arm=arm)
    recomputed = rounded(_summarize_m4_results(results))
    if not _summaries_match(recomputed, report.get("summary")):
        raise ValueError("M4 report summary does not match recomputation from result rows.")
    _validate_reranker_cost_report(
        run,
        scored_cost=recomputed["costUsd"]["reranker"],
    )
    return report


def _validate_report_bindings(report: dict[str, Any], *, arm: str) -> None:
    suite = report["suite"]
    run = report["run"]
    config = run.get("resolvedConfig")
    if not isinstance(config, dict) or run.get("configFingerprint") != sha256_json(config):
        raise ValueError("M4 report config fingerprint is invalid.")
    experiment = m4_experiment_fingerprint(config)
    if run.get("m4ExperimentFingerprint") != experiment:
        raise ValueError("M4 report experiment fingerprint is invalid.")
    reranker_fingerprint = reranker_config_fingerprint(config)
    if run.get("rerankerConfigFingerprint") != reranker_fingerprint:
        raise ValueError("M4 report reranker config fingerprint is invalid.")
    provider = _reranker_provider(config)
    if arm == "control" and provider != "heuristic-multi-signal":
        raise ValueError("M4 control must use heuristic-multi-signal reranking.")
    if arm == "treatment" and provider in {"disabled", "heuristic-multi-signal"}:
        raise ValueError("M4 treatment must use a learned reranker provider.")

    contract = suite.get("judgmentContract")
    if (
        not isinstance(contract, dict)
        or contract.get("policyVersion") != M4_JUDGMENT_POLICY_VERSION
        or suite.get("judgmentContractSha256") != sha256_json(contract)
        or contract.get("sourceSplit") != "dev"
        or contract.get("m1PolicyHoldoutUsed") is not False
        or contract.get("m1PolicyHoldoutForbidden") is not True
        or contract.get("unjudgedReturnedPolicy") != "fail-closed"
        or contract.get("selectionLeakageWarning") != M4_SELECTION_LEAKAGE_WARNING
    ):
        raise ValueError("M4 report violates its schema-v5 Dev judgment contract.")
    if experiment != contract.get("experimentFingerprint"):
        raise ValueError("M4 report differs from the frozen pre-rerank experiment.")
    expected_capture = {
        "scopedSourceSha256": contract["captureScopedSourceSha256"],
        "sourceGitSha": contract["captureSourceGitSha"],
        "runtimeEnvironment": contract["captureRuntimeEnvironment"],
        "runtimeEnvironmentFingerprint": contract[
            "captureRuntimeEnvironmentFingerprint"
        ],
        "qdrantServer": contract["captureQdrantServer"],
        "qdrantServerFingerprint": contract["captureQdrantServerFingerprint"],
        "indexManifestFingerprint": contract["captureIndexManifestFingerprint"],
        "embeddingIdentity": contract["embeddingIdentity"],
        "rewriteConfigFingerprint": contract["rewriteConfigFingerprint"],
        "rewritePromptFingerprint": contract["rewritePromptFingerprint"],
    }
    source = run.get("scopedSource") or {}
    runtime = run.get("runtimeEnvironment") or {}
    git = run.get("git") or {}
    qdrant = (report.get("index") or {}).get("qdrantServer") or {}
    observed_capture = {
        "scopedSourceSha256": source.get("sha256"),
        "sourceGitSha": git.get("sha"),
        "runtimeEnvironment": runtime,
        "runtimeEnvironmentFingerprint": sha256_json(runtime),
        "qdrantServer": qdrant,
        "qdrantServerFingerprint": sha256_json(qdrant),
        "indexManifestFingerprint": (report.get("index") or {}).get(
            "manifestFingerprint"
        ),
        "embeddingIdentity": (config.get("embedding") or {}).get("identity"),
        "rewriteConfigFingerprint": run.get("rewriteConfigFingerprint"),
        "rewritePromptFingerprint": run.get("promptFingerprint"),
    }
    if observed_capture != expected_capture:
        raise ValueError("M4 report source/runtime/index/rewrite identity differs from capture.")
    if (
        not isinstance(source.get("fileSha256"), dict)
        or source.get("sha256") != sha256_json(source["fileSha256"])
        or source.get("dirty") is not False
        or git.get("dirty") is not False
    ):
        raise ValueError("M4 formal report requires clean source and Git identities.")

    manifest = report.get("evaluationManifest")
    if not isinstance(manifest, dict):
        raise ValueError("M4 report is missing its evaluation manifest.")
    expected_manifest = {
        "suiteSchemaVersion": 5,
        "suiteContractSha256": suite["suiteContractSha256"],
        "caseSha256": suite["caseSha256"],
        "judgmentContractSha256": suite["judgmentContractSha256"],
        "candidateUniverseFixtureSha256": contract[
            "candidateUniverseFixtureSha256"
        ],
        "candidatePoolContractSha256": contract["candidatePoolContractSha256"],
        "configFingerprint": run["configFingerprint"],
        "m4ExperimentFingerprint": experiment,
        "rerankerConfigFingerprint": reranker_fingerprint,
        "rerankerProvider": provider,
        "indexManifestFingerprint": report["index"]["manifestFingerprint"],
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise ValueError(f"M4 evaluation manifest {field} does not match its report.")


def _validate_result_pool_bindings(report: dict[str, Any], *, arm: str) -> None:
    contract = report["suite"]["judgmentContract"]
    rows = []
    for result in report["results"]:
        case_id = str(result["id"])
        pool_ids, pool_fingerprint, input_fingerprint = extract_pre_rerank_contract(
            result,
            case_id=case_id,
        )
        if len(pool_ids) > int(contract["candidateLimit"]):
            raise ValueError(f"M4 {arm} case {case_id} exceeds the frozen pre-rerank bound.")
        returned = [
            str(item.get("externalId")) for item in result.get("orderedCandidates") or []
        ]
        if len(returned) > int(contract["finalCandidateLimit"]):
            raise ValueError(f"M4 {arm} case {case_id} exceeds the final Top-10 bound.")
        if not set(returned) <= set(pool_ids):
            raise ValueError(f"M4 {arm} case {case_id} returned a merchant outside the frozen pool.")
        requests = result.get("requests") or {}
        reranker_requests = requests.get("rerankerRequests", 0)
        _require_exact_integer(reranker_requests, label=f"M4 {arm} rerankerRequests")
        usage = requests.get("rerankerProviderUsage") or {}
        if not isinstance(usage, dict):
            raise ValueError("M4 rerankerProviderUsage must be an object.")
        for field in _RERANKER_PROVIDER_USAGE_FIELDS:
            _require_exact_integer(
                usage.get(field, 0), label=f"M4 rerankerProviderUsage.{field}"
            )
        _finite_nonnegative_float(
            usage.get("estimated_cost_usd"),
            label="M4 rerankerProviderUsage.estimated_cost_usd",
        )
        fallback = requests.get("rerankerFallback", False)
        if not isinstance(fallback, bool):
            raise ValueError("M4 rerankerFallback must be boolean.")
        if arm == "control":
            if reranker_requests != 0 or usage["network_requests"] != 0 or fallback:
                raise ValueError("M4 heuristic control may not call or fall back from a provider.")
        elif (
            reranker_requests != 1
            or usage["network_requests"] != 1
            or usage["retry_count"] != 0
            or usage["failure_count"] != 0
            or fallback
            or int((result.get("retrievalTrace") or {}).get("rerankerCandidates") or 0)
            != len(pool_ids)
        ):
            raise ValueError(
                "M4 learned treatment requires exactly one successful reranker batch per case."
            )
        rows.append(
            {
                "id": case_id,
                "preRerankCandidateExternalIds": pool_ids,
                "preRerankPoolFingerprint": pool_fingerprint,
                "rerankerInputFingerprint": input_fingerprint,
            }
        )
    if sha256_json(rows) != contract.get("candidatePoolContractSha256"):
        raise ValueError(f"M4 {arm} report does not replay the frozen candidate/input pool.")


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
        raise ValueError("M4 control/treatment reports use different frozen suites.")
    if control["suite"].get("judgmentContract") != treatment["suite"].get(
        "judgmentContract"
    ):
        raise ValueError("M4 control/treatment reports use different judgment contracts.")
    if [str(item["id"]) for item in control["results"]] != [
        str(item["id"]) for item in treatment["results"]
    ]:
        raise ValueError("M4 control/treatment result order or IDs differ.")
    for report in (control, treatment):
        observed_gate = ((report.get("run") or {}).get("policyArtifacts") or {}).get(
            "qualityGateSha256"
        )
        if observed_gate != gate_sha256:
            raise ValueError("M4 report is not bound to the committed quality gate.")
    control_run = control["run"]
    treatment_run = treatment["run"]
    if m4_experiment_fingerprint(
        control_run["resolvedConfig"]
    ) != m4_experiment_fingerprint(treatment_run["resolvedConfig"]):
        raise ValueError("M4 arms differ outside the isolated reranker configuration.")
    if control_run["m4ExperimentFingerprint"] != treatment_run["m4ExperimentFingerprint"]:
        raise ValueError("M4 arms use different experiment fingerprints.")
    for field, label in (
        ("scopedSource", "source snapshots"),
        ("git", "Git identities"),
        ("runtimeEnvironment", "runtime environments"),
    ):
        if control_run[field] != treatment_run[field]:
            raise ValueError(f"M4 arms use different {label}.")
    if control["index"] != treatment["index"]:
        raise ValueError("M4 arms did not reuse the exact same frozen index.")
    control_contracts = [
        extract_pre_rerank_contract(row, case_id=str(row["id"]))
        for row in control["results"]
    ]
    treatment_contracts = [
        extract_pre_rerank_contract(row, case_id=str(row["id"]))
        for row in treatment["results"]
    ]
    if control_contracts != treatment_contracts:
        raise ValueError("M4 arms used different pre-rerank pools or reranker inputs.")


def _summarize_m4_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    for result in results:
        for section in ("metrics", "integrity"):
            values = result.get(section) or {}
            for field, value in values.items():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"M4 {section}.{field} must be finite.")
    summary = summarize_results(results)
    request_counts = summary["requestCounts"]
    request_counts.update(
        {
            "rerankerProviderNetworkRequests": sum(
                int((row["requests"].get("rerankerProviderUsage") or {}).get("network_requests", 0))
                for row in results
            ),
            "rerankerProviderTokens": sum(
                int((row["requests"].get("rerankerProviderUsage") or {}).get("total_tokens", 0))
                for row in results
            ),
            "rerankerProviderRetries": sum(
                int((row["requests"].get("rerankerProviderUsage") or {}).get("retry_count", 0))
                for row in results
            ),
            "rerankerProviderFailures": sum(
                int((row["requests"].get("rerankerProviderUsage") or {}).get("failure_count", 0))
                for row in results
            ),
            "rerankerCacheHits": sum(
                int((row["requests"].get("rerankerProviderUsage") or {}).get("cache_hits", 0))
                for row in results
            ),
            "rerankerFallbacks": sum(
                bool(row["requests"].get("rerankerFallback", False)) for row in results
            ),
        }
    )
    summary.setdefault("costUsd", {})["reranker"] = sum(
        float(
            (row["requests"].get("rerankerProviderUsage") or {})[
                "estimated_cost_usd"
            ]
        )
        for row in results
    )
    return summary


def _validate_reranker_cost_report(run: dict[str, Any], *, scored_cost: float) -> None:
    cost = run.get("rerankerProviderCost")
    expected = {
        "scoredEstimatedCostUsd",
        "warmupEstimatedCostUsd",
        "estimatedCostUsd",
        "hardCostCapUsd",
    }
    if not isinstance(cost, dict) or cost.keys() != expected:
        raise ValueError("M4 report is missing its exact reranker provider cost contract.")
    for field in expected:
        _finite_nonnegative_float(cost[field], label=f"M4 rerankerProviderCost.{field}")
    if not math.isclose(
        cost["scoredEstimatedCostUsd"],
        scored_cost,
        rel_tol=0.0,
        abs_tol=_FLOAT_ABS_TOLERANCE,
    ):
        raise ValueError("M4 scored reranker cost does not match result-row usage.")
    if not math.isclose(
        cost["estimatedCostUsd"],
        cost["scoredEstimatedCostUsd"] + cost["warmupEstimatedCostUsd"],
        rel_tol=0.0,
        abs_tol=_FLOAT_ABS_TOLERANCE,
    ):
        raise ValueError("M4 total reranker cost does not equal scored plus warmup cost.")


def _validate_budget_contract(gate: dict[str, Any], *, case_count: int) -> dict[str, Any]:
    budget = gate.get("budgetContract")
    if not isinstance(budget, dict):
        raise ValueError("M4 quality gate is missing its budget contract.")
    for field in (
        "maximumCases",
        "preRerankCandidateLimit",
        "finalCandidateLimit",
        "maxTreatmentRerankerNetworkRequests",
        "maxTreatmentRerankerTokens",
    ):
        _require_exact_integer(budget.get(field), label=f"M4 budgetContract.{field}")
    if case_count > budget["maximumCases"]:
        raise ValueError("M4 suite exceeds the frozen case budget.")
    if (
        budget["preRerankCandidateLimit"] != 30
        or budget["finalCandidateLimit"] != 10
        or budget["maxTreatmentRerankerNetworkRequests"] != budget["maximumCases"]
    ):
        raise ValueError("M4 quality gate has an inconsistent one-batch-per-case budget.")
    _finite_nonnegative_float(
        float(budget.get("maxRerankerEstimatedCostUsd")),
        label="M4 budgetContract.maxRerankerEstimatedCostUsd",
    )
    return budget


def _latency_observation(
    control_summary: dict[str, Any], treatment_summary: dict[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "policy": "quality-accepted-under-latency-waiver",
        "gating": False,
    }
    for stage in ("total", "reranker"):
        control = ((control_summary.get("latencyMs") or {}).get(stage) or {}).get("p95")
        treatment = ((treatment_summary.get("latencyMs") or {}).get(stage) or {}).get("p95")
        if isinstance(treatment, (int, float)) and not isinstance(treatment, bool):
            stage_result: dict[str, Any] = {"treatmentP95Ms": float(treatment)}
            if isinstance(control, (int, float)) and not isinstance(control, bool):
                stage_result["controlP95Ms"] = float(control)
                stage_result["ratio"] = float(treatment) / float(control) if control > 0 else None
            output[stage] = stage_result
    return output


def _reranker_provider(config: dict[str, Any]) -> str:
    reranker = config.get("reranker")
    provider = reranker.get("provider") if isinstance(reranker, dict) else None
    if provider is None:
        provider = (config.get("features") or {}).get("rerankerProvider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("M4 report is missing its reranker provider.")
    return provider


def _summaries_match(expected: Any, observed: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(observed, dict) and expected.keys() == observed.keys() and all(
            _summaries_match(value, observed[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and len(expected) == len(observed) and all(
            _summaries_match(left, right)
            for left, right in zip(expected, observed, strict=True)
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
            and math.isclose(expected, observed, rel_tol=0.0, abs_tol=_FLOAT_ABS_TOLERANCE)
        )
    return expected == observed


def _linear_quantile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("M4 quantile requires values.")
    position = quantile * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _finite_number_path(value: dict[str, Any], path: str) -> float:
    observed = _path(value, path)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise ValueError(f"M4 gate path {path!r} is not numeric.")
    result = float(observed)
    if not math.isfinite(result):
        raise ValueError(f"M4 gate path {path!r} is non-finite.")
    return result


def _integer_path(value: dict[str, Any], path: str) -> int:
    observed = _path(value, path)
    _require_exact_integer(observed, label=f"M4 gate path {path}")
    return observed


def _path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise ValueError(f"M4 gate path {path!r} is missing.")
        current = current[segment]
    if current is None:
        raise ValueError(f"M4 gate path {path!r} is not measurable.")
    return current


def _finite_gate_number(value: Any, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"M4 gate threshold {path!r} is not numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"M4 gate threshold {path!r} is non-finite.")
    return result


def _finite_probability(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric.")
    result = float(value)
    if not 0.0 < result < 1.0:
        raise ValueError(f"{label} must be between zero and one.")
    return result


def _finite_nonnegative_float(value: Any, *, label: str) -> float:
    if not isinstance(value, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite non-negative float.")
    return value


def _positive_integer(value: Any, *, label: str) -> int:
    _require_exact_integer(value, label=label)
    if value == 0:
        raise ValueError(f"{label} must be positive.")
    return value


def _nonnegative_integer(value: Any, *, label: str) -> int:
    _require_exact_integer(value, label=label)
    return value


def _exact_gate_integer(value: Any, *, path: str) -> int:
    _require_exact_integer(value, label=f"M4 gate threshold {path}")
    return value


def _require_exact_integer(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare frozen M4 heuristic control and learned-reranker treatment."
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
