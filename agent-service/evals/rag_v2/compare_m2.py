from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.rag_v2.metrics import rounded, summarize_results

POLICY_VERSION = "rag-v2-m2-control-treatment-v1"
DEFAULT_GATE = Path(__file__).resolve().parent / "m2_quality_gate.json"


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
        raise ValueError("M2 comparison requires the committed m2_quality_gate.json.")
    _validate_pair(control, treatment, gate_sha256=gate_sha256)

    control_summary = control["summary"]
    treatment_summary = treatment["summary"]
    failures: list[str] = []
    comparison_gate = gate.get("comparison") or {}
    deltas: dict[str, float] = {}
    for path, minimum in (comparison_gate.get("minDeltas") or {}).items():
        delta = float(_path(treatment_summary, path)) - float(_path(control_summary, path))
        deltas[path] = delta
        if delta < float(minimum):
            failures.append(f"{path} delta={delta:.6f} is below {minimum}")
    for path, maximum_drop in (comparison_gate.get("maxDrops") or {}).items():
        drop = float(_path(control_summary, path)) - float(_path(treatment_summary, path))
        deltas.setdefault(path, -drop)
        if drop > float(maximum_drop):
            failures.append(f"{path} dropped {drop:.6f}; maximum is {maximum_drop}")
    for path, minimum in (comparison_gate.get("treatmentMinimums") or {}).items():
        value = float(_path(treatment_summary, path))
        if value < float(minimum):
            failures.append(f"treatment {path}={value:.6f} is below {minimum}")
    for path, maximum in (comparison_gate.get("treatmentMaximums") or {}).items():
        value = float(_path(treatment_summary, path))
        if value > float(maximum):
            failures.append(f"treatment {path}={value:.6f} exceeds {maximum}")
    ratios: dict[str, float] = {}
    for path, maximum_ratio in (comparison_gate.get("maxRatios") or {}).items():
        control_value = float(_path(control_summary, path))
        treatment_value = float(_path(treatment_summary, path))
        ratio = treatment_value / control_value if control_value > 0 else float("inf")
        ratios[path] = ratio
        if ratio > float(maximum_ratio):
            failures.append(f"{path} ratio={ratio:.6f} exceeds {maximum_ratio}")
    request_deltas: dict[str, int] = {}
    for path, maximum_increase in (comparison_gate.get("maxIncreases") or {}).items():
        increase = int(_path(treatment_summary, path)) - int(_path(control_summary, path))
        request_deltas[path] = increase
        if increase > int(maximum_increase):
            failures.append(f"{path} increased by {increase}; maximum is {maximum_increase}")

    case_deltas = []
    control_by_id = {item["id"]: item for item in control["results"]}
    for treatment_case in treatment["results"]:
        control_case = control_by_id[treatment_case["id"]]
        case_deltas.append(
            {
                "id": treatment_case["id"],
                "recallAt10": (
                    float(treatment_case["metrics"]["recallAt10"])
                    - float(control_case["metrics"]["recallAt10"])
                ),
                "ndcgAt10": (
                    float(treatment_case["metrics"]["ndcgAt10"]) - float(control_case["metrics"]["ndcgAt10"])
                ),
                "structuredMissRecoveredAt10": int(
                    (treatment_case.get("structuredMissRescue") or {}).get("recoveredAt10Count", 0)
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
                "sha256": _file_sha256(gate_path),
            },
            "experimentFingerprint": control["run"]["m2ExperimentFingerprint"],
            "controlConfigFingerprint": control["run"]["configFingerprint"],
            "treatmentConfigFingerprint": treatment["run"]["configFingerprint"],
            "indexManifestFingerprint": control["index"]["manifestFingerprint"],
        },
        "deltas": deltas,
        "ratios": ratios,
        "requestDeltas": request_deltas,
        "control": {
            "mode": "candidate-filtered",
            "summary": control_summary,
        },
        "treatment": {
            "mode": "global-hybrid",
            "summary": treatment_summary,
        },
        "caseDeltas": case_deltas,
        "thresholds": gate,
    }
    return rounded(output)


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    suite = report.get("suite") or {}
    run = report.get("run") or {}
    results = report.get("results") or []
    if int(report.get("schemaVersion") or 0) < 3:
        raise ValueError(f"M2 report must use schemaVersion>=3: {path}")
    if suite.get("split") != "dev" or not suite.get("judgmentContractSha256"):
        raise ValueError("M2 comparison only accepts the schema-v3 Dev judgment contract.")
    if bool(run.get("partial")) or int(run.get("evaluatedCases") or 0) != int(suite.get("caseCount") or 0):
        raise ValueError("M2 comparison requires a complete report.")
    if len(results) != int(suite["caseCount"]):
        raise ValueError("M2 report result count does not match its suite.")
    if (report.get("qualityGate") or {}).get("passed") is not True:
        raise ValueError("Each M2 arm must pass its per-run quality gate.")
    if (
        int(run.get("embeddingFallbackCount") or 0)
        or int(run.get("retrievalFallbackCount") or 0)
        or int(run.get("retrievalIdentityConflictCount") or 0)
        or int(run.get("retrievalSafetyRejectionCount") or 0)
    ):
        raise ValueError("M2 comparison rejects embedding or retrieval branch fallbacks.")
    if any(
        not bool(candidate.get("judged"))
        for result in results
        for candidate in result.get("orderedCandidates") or []
    ):
        raise ValueError("M2 report contains an unjudged returned merchant.")
    recomputed = rounded(summarize_results(results))
    if not _summaries_match(recomputed, report.get("summary")):
        raise ValueError("M2 report summary does not match recomputation from result rows.")
    return report


def _summaries_match(expected: Any, observed: Any) -> bool:
    """Allow only the one-unit drift caused by serializing six-decimal case metrics."""

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
            and math.isclose(expected, observed, rel_tol=0.0, abs_tol=1.1e-6)
        )
    return expected == observed


def _validate_pair(
    control: dict[str, Any],
    treatment: dict[str, Any],
    *,
    gate_sha256: str,
) -> None:
    suite_fields = (
        "suite",
        "split",
        "caseCount",
        "caseSha256",
        "suiteContractSha256",
        "judgmentContractSha256",
    )
    if any(control["suite"].get(field) != treatment["suite"].get(field) for field in suite_fields):
        raise ValueError("M2 control/treatment reports use different frozen suites.")
    if control["suite"].get("split") != "dev":
        raise ValueError("M2 comparison cannot consume the M1 policy holdout.")
    for report in (control, treatment):
        _validate_report_bindings(report)
        observed_gate = (
            (report.get("run") or {}).get("policyArtifacts") or {}
        ).get("qualityGateSha256")
        if observed_gate != gate_sha256:
            raise ValueError("M2 report is not bound to the committed quality gate.")
    control_features = control["run"]["resolvedConfig"]["features"]
    treatment_features = treatment["run"]["resolvedConfig"]["features"]
    if (
        control_features.get("globalRetrievalMode") != "candidate-filtered"
        or control_features.get("globalRetrievalEnabled") is not False
    ):
        raise ValueError("M2 control must explicitly disable candidate-filtered global retrieval.")
    if (
        treatment_features.get("globalRetrievalMode") != "global-hybrid"
        or treatment_features.get("globalRetrievalEnabled") is not True
    ):
        raise ValueError("M2 treatment must explicitly enable global-hybrid retrieval.")
    if control["run"].get("m2ExperimentFingerprint") != treatment["run"].get("m2ExperimentFingerprint"):
        raise ValueError("M2 arms differ outside the isolated global-retrieval flag.")
    control_source = control["run"]["scopedSource"]
    treatment_source = treatment["run"]["scopedSource"]
    if (
        control_source.get("sha256") != treatment_source.get("sha256")
        or control_source.get("fileSha256") != treatment_source.get("fileSha256")
    ):
        raise ValueError("M2 arms use different Eval/retrieval source snapshots.")
    if control["run"]["runtimeEnvironment"] != treatment["run"]["runtimeEnvironment"]:
        raise ValueError("M2 arms use different Python/qdrant-client environments.")
    if control["index"].get("qdrantServer") != treatment["index"].get("qdrantServer"):
        raise ValueError("M2 arms use different Qdrant Server metadata.")
    if control["index"].get("manifestFingerprint") != treatment["index"].get("manifestFingerprint"):
        raise ValueError("M2 arms did not reuse the exact same frozen index manifest.")
    if (
        control["index"].get("lifecycleState") != "complete"
        or treatment["index"].get("lifecycleState") != "complete"
    ):
        raise ValueError("M2 comparison requires a complete, ready index in both arms.")


def _validate_report_bindings(report: dict[str, Any]) -> None:
    suite = report["suite"]
    run = report["run"]
    resolved_config = run.get("resolvedConfig")
    if not isinstance(resolved_config, dict):
        raise ValueError("M2 report is missing its resolved configuration.")
    config_fingerprint = _fingerprint(resolved_config)
    if run.get("configFingerprint") != config_fingerprint:
        raise ValueError("M2 report config fingerprint does not match its resolved configuration.")
    experiment_fingerprint = _m2_experiment_fingerprint(resolved_config)
    if run.get("m2ExperimentFingerprint") != experiment_fingerprint:
        raise ValueError("M2 report experiment fingerprint does not match its resolved configuration.")

    scoped_source = run.get("scopedSource")
    if not isinstance(scoped_source, dict) or not isinstance(scoped_source.get("fileSha256"), dict):
        raise ValueError("M2 report is missing its scoped source file manifest.")
    if scoped_source.get("sha256") != _fingerprint(scoped_source["fileSha256"]):
        raise ValueError("M2 report scoped source SHA does not match its file manifest.")

    judgment_contract = suite.get("judgmentContract")
    if not isinstance(judgment_contract, dict):
        raise ValueError("M2 report is missing its bounded judgment contract.")
    judgment_sha256 = _fingerprint(judgment_contract)
    if suite.get("judgmentContractSha256") != judgment_sha256:
        raise ValueError("M2 report judgment contract SHA is invalid.")
    runtime_environment = run.get("runtimeEnvironment")
    if not isinstance(runtime_environment, dict) or not runtime_environment.get(
        "qdrantClientVersion"
    ):
        raise ValueError("M2 report is missing its Python/qdrant-client environment.")
    qdrant_server = report["index"].get("qdrantServer")
    if not isinstance(qdrant_server, dict) or not qdrant_server.get("mode"):
        raise ValueError("M2 report is missing Qdrant Server metadata.")
    if judgment_contract.get("captureRuntimeEnvironment") != runtime_environment:
        raise ValueError("M2 runtime environment differs from candidate capture.")
    if judgment_contract.get("captureQdrantServer") != qdrant_server:
        raise ValueError("M2 Qdrant Server metadata differs from candidate capture.")

    manifest = report.get("evaluationManifest")
    if not isinstance(manifest, dict):
        raise ValueError("M2 report is missing its evaluation manifest.")
    expected_manifest = {
        "suiteSchemaVersion": int(suite["schemaVersion"]),
        "suiteContractSha256": suite["suiteContractSha256"],
        "caseSha256": suite["caseSha256"],
        "judgmentContractSha256": judgment_sha256,
        "candidateUniverseFixtureSha256": judgment_contract[
            "candidateUniverseFixtureSha256"
        ],
        "configFingerprint": config_fingerprint,
        "m2ExperimentFingerprint": experiment_fingerprint,
        "scopedSourceSha256": scoped_source["sha256"],
        "runtimeEnvironmentFingerprint": _fingerprint(runtime_environment),
        "indexManifestFingerprint": report["index"]["manifestFingerprint"],
        "qdrantServerFingerprint": _fingerprint(qdrant_server),
        "embeddingIdentity": (resolved_config.get("embedding") or {}).get("identity"),
        "retrievalMode": (resolved_config.get("retrieval") or {}).get("mode"),
        "globalRetrievalEnabled": (resolved_config.get("features") or {}).get(
            "globalRetrievalEnabled"
        ),
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise ValueError(f"M2 evaluation manifest {field} does not match its report.")


def _m2_experiment_fingerprint(config: dict[str, Any]) -> str:
    value = json.loads(json.dumps(config))
    value.pop("experimentControlFingerprint", None)
    (value.get("retrieval") or {}).pop("mode", None)
    features = value.get("features") or {}
    features.pop("globalRetrievalMode", None)
    features.pop("globalRetrievalEnabled", None)
    return _fingerprint(value)


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for segment in path.split("."):
        current = current[segment]
    if current is None:
        raise ValueError(f"M2 gate path {path!r} is not measurable for this suite.")
    return current


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare frozen M2 candidate-filtered control and global-hybrid treatment."
    )
    parser.add_argument("control", type=Path)
    parser.add_argument("treatment", type=Path)
    parser.add_argument("--quality-gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite M2 comparison: {args.output}")
    result = compare(args.control, args.treatment, gate_path=args.quality_gate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
