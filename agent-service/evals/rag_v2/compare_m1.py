from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.rag.embeddings import EmbeddingMetadata
from evals.rag_v2.contract import suite_contract_sha256
from evals.rag_v2.embedding_profiles import PROFILES, EmbeddingProfile

POLICY_VERSION = "m1-embedding-selection-v2"
EVAL_DIRECTORY = Path(__file__).resolve().parent
FROZEN_BASELINE_PATH = EVAL_DIRECTORY / "baseline.hash64.local.json"
FROZEN_QUALITY_GATE_PATH = EVAL_DIRECTORY / "quality_gate.json"
FROZEN_DEV_SUITE_PATH = EVAL_DIRECTORY / "cases.dev.json"
EXPECTED_PROFILES = {
    "openai-small-1024",
    "openai-large-1024",
    "qwen37-1024",
}
BILINGUAL_TIE_BAND = 0.005
MIN_BILINGUAL_GAIN_VS_HASH = 0.005
BOOTSTRAP_SEED = 20260831
BOOTSTRAP_SAMPLES = 5_000
SUMMARY_TOLERANCE = 2e-6


def compare(report_paths: list[Path]) -> dict[str, Any]:
    artifacts = _load_policy_artifacts()
    reports = [_load_report(path) for path in report_paths]
    controls = _validate_comparable(reports, artifacts)
    baseline = artifacts["baselineMetrics"]
    rows = [_score_report(report, path, baseline) for report, path in zip(reports, report_paths, strict=True)]
    eligible = [row for row in rows if row["meetsHashImprovementGate"]]
    if not eligible:
        raise ValueError(
            "No M1 candidate improves both bilingual nDCG@10 and MRR@10 over the "
            f"frozen Hash baseline by at least {MIN_BILINGUAL_GAIN_VS_HASH:.3f}."
        )
    best_bilingual = max(row["bilingualNdcgAt10"] for row in eligible)
    contenders = [row for row in eligible if row["bilingualNdcgAt10"] >= best_bilingual - BILINGUAL_TIE_BAND]
    contenders.sort(
        key=lambda row: (
            -row["overallNdcgAt10"],
            -row["bilingualMrrAt10"],
            row["estimatedCostUsd"],
            row["embeddingP95Ms"],
            row["profileId"],
        )
    )
    winner = contenders[0]
    reports_by_profile = {
        report["run"]["resolvedConfig"]["embedding"]["profileId"]: report for report in reports
    }
    winner_report = reports_by_profile[winner["profileId"]]
    paired = {
        profile_id: _paired_bootstrap(winner_report, report)
        for profile_id, report in sorted(reports_by_profile.items())
        if profile_id != winner["profileId"]
    }
    winner_control = normalized_dev_control(
        winner_report["run"]["resolvedConfig"],
        include_collection=True,
    )
    return {
        "schemaVersion": 2,
        "policyVersion": POLICY_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "policy": {
            "eligibility": (
                "complete frozen Dev report; committed baseline and gate; quality gate pass; "
                "1024d frozen profile metadata; 145000 ready points; zero embedding fallback; "
                "identical result IDs, source, and normalized experiment control; bilingual "
                "nDCG@10 and MRR@10 each improve over Hash by >= 0.005"
            ),
            "primary": "case-count-weighted zh+mixed nDCG@10 recomputed from result rows",
            "hashImprovement": {
                "minimumAbsoluteGain": MIN_BILINGUAL_GAIN_VS_HASH,
                "baselineBilingualNdcgAt10": baseline["bilingualNdcgAt10"],
                "baselineBilingualMrrAt10": baseline["bilingualMrrAt10"],
            },
            "tieBand": BILINGUAL_TIE_BAND,
            "tieBreakers": [
                "overall nDCG@10 desc",
                "case-count-weighted zh+mixed MRR@10 desc",
                "estimated provider cost asc",
                "embedding P95 asc",
                "profile id asc",
            ],
            "bootstrap": {
                "seed": BOOTSTRAP_SEED,
                "samples": BOOTSTRAP_SAMPLES,
                "confidence": 0.95,
            },
        },
        "frozenArtifacts": artifacts["fingerprints"],
        "comparisonControl": controls[0],
        "comparisonControlFingerprint": _fingerprint(controls[0]),
        "suite": reports[0]["suite"],
        "candidates": sorted(rows, key=lambda row: row["profileId"]),
        "winnerProfileId": winner["profileId"],
        "winnerEmbedding": winner_report["run"]["resolvedConfig"]["embedding"],
        "winnerDevConfigFingerprint": winner_report["run"]["configFingerprint"],
        "devScopedSourceSha256": winner_report["run"]["scopedSource"]["sha256"],
        "winnerDevControl": winner_control,
        "winnerDevControlFingerprint": _fingerprint(winner_control),
        "pairedWinnerDeltas": paired,
        "devReports": {
            report["run"]["resolvedConfig"]["embedding"]["profileId"]: {
                "filename": path.name,
                "sha256": _sha256_file(path),
            }
            for report, path in sorted(
                zip(reports, report_paths, strict=True),
                key=lambda item: item[0]["run"]["resolvedConfig"]["embedding"]["profileId"],
            )
        },
    }


def _load_policy_artifacts() -> dict[str, Any]:
    baseline = _load_report(FROZEN_BASELINE_PATH)
    gate = _load_report(FROZEN_QUALITY_GATE_PATH)
    suite = _load_report(FROZEN_DEV_SUITE_PATH)
    if baseline.get("status") != "frozen-m0-baseline":
        raise ValueError("Committed M0 baseline manifest is not frozen.")
    if gate.get("status") != "m0-baseline-invariants":
        raise ValueError("Committed quality gate has an unexpected policy status.")
    if suite.get("split") != "dev" or int(suite.get("caseCount") or 0) != 80:
        raise ValueError("Committed M1 Dev suite must contain exactly 80 Dev cases.")
    cases = suite.get("cases") or []
    actual_case_sha = hashlib.sha256(_canonical_json(cases).encode("utf-8")).hexdigest()
    if suite.get("caseSha256") != actual_case_sha:
        raise ValueError("Committed Dev suite case SHA is invalid.")
    if suite.get("suiteContractSha256") != suite_contract_sha256(suite):
        raise ValueError("Committed Dev suite contract SHA is invalid.")

    frozen_dev = (baseline.get("splits") or {}).get("dev") or {}
    corpus = baseline.get("corpus") or {}
    if (
        int(frozen_dev.get("caseCount") or 0) != 80
        or frozen_dev.get("caseSha256") != suite["caseSha256"]
        or frozen_dev.get("suiteContractSha256") != suite["suiteContractSha256"]
        or corpus.get("datasetSha256") != suite.get("datasetSha256")
        or int(corpus.get("indexedDocuments") or 0) != 145_000
    ):
        raise ValueError("Committed baseline manifest does not bind the frozen M1 Dev suite.")
    language_ndcg = frozen_dev.get("languageNdcgAt10") or {}
    language_mrr = frozen_dev.get("languageMrrAt10") or {}
    for language in ("zh", "mixed"):
        _finite_rate(language_ndcg.get(language), f"baseline {language} nDCG@10")
        _finite_rate(language_mrr.get(language), f"baseline {language} MRR@10")
    zh_count, mixed_count = 30, 10
    baseline_metrics = {
        "bilingualNdcgAt10": (
            float(language_ndcg["zh"]) * zh_count + float(language_ndcg["mixed"]) * mixed_count
        )
        / (zh_count + mixed_count),
        "bilingualMrrAt10": (
            float(language_mrr["zh"]) * zh_count + float(language_mrr["mixed"]) * mixed_count
        )
        / (zh_count + mixed_count),
    }
    case_languages = {str(case["id"]): str(case["language"]) for case in cases}
    if len(case_languages) != 80:
        raise ValueError("Committed Dev suite contains duplicate case IDs.")
    fingerprints = {
        "baselineManifest": {
            "filename": FROZEN_BASELINE_PATH.name,
            "sha256": _sha256_file(FROZEN_BASELINE_PATH),
            "frozenDevReportSha256": ((baseline.get("reports") or {}).get("dev") or {}).get("sha256"),
        },
        "qualityGate": {
            "filename": FROZEN_QUALITY_GATE_PATH.name,
            "sha256": _sha256_file(FROZEN_QUALITY_GATE_PATH),
        },
        "devSuite": {
            "filename": FROZEN_DEV_SUITE_PATH.name,
            "sha256": _sha256_file(FROZEN_DEV_SUITE_PATH),
            "caseSha256": suite["caseSha256"],
            "suiteContractSha256": suite["suiteContractSha256"],
        },
    }
    if not _is_sha256(fingerprints["baselineManifest"]["frozenDevReportSha256"]):
        raise ValueError("Committed baseline manifest is missing its frozen Dev report SHA.")
    return {
        "baseline": baseline,
        "gate": gate,
        "suite": suite,
        "caseLanguages": case_languages,
        "baselineMetrics": baseline_metrics,
        "fingerprints": fingerprints,
    }


def _validate_comparable(reports: list[dict], artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    if len(reports) != len(EXPECTED_PROFILES):
        raise ValueError("M1 selection requires exactly three Dev reports.")
    profiles = {report["run"]["resolvedConfig"]["embedding"].get("profileId") for report in reports}
    if profiles != EXPECTED_PROFILES:
        raise ValueError(f"M1 reports must cover exactly {sorted(EXPECTED_PROFILES)}.")
    frozen_suite = artifacts["suite"]
    reference = reports[0]
    source = reference["run"]["scopedSource"]["sha256"]
    if not _is_sha256(source):
        raise ValueError("M1 report is missing a valid scoped source SHA-256.")
    controls: list[dict[str, Any]] = []
    for report in reports:
        suite = report.get("suite") or {}
        if (
            suite.get("split") != "dev"
            or int(suite.get("caseCount") or 0) != 80
            or suite.get("caseSha256") != frozen_suite["caseSha256"]
            or suite.get("suiteContractSha256") != frozen_suite["suiteContractSha256"]
            or suite.get("datasetSha256") != frozen_suite["datasetSha256"]
            or suite.get("dataVersion") != frozen_suite["dataVersion"]
        ):
            raise ValueError("M1 candidate report does not use the committed frozen Dev suite.")
        run = report["run"]
        if run.get("partial") or int(run.get("evaluatedCases") or 0) != 80:
            raise ValueError("M1 selection rejects partial Dev reports.")
        if run["scopedSource"]["sha256"] != source:
            raise ValueError("M1 reports were produced from different scoped source versions.")
        if report["qualityGate"].get("passed") is not True:
            raise ValueError("M1 selection rejects a candidate that failed its quality gate.")
        if report["qualityGate"].get("relativeStatus") != "evaluated":
            raise ValueError("M1 selection requires evaluation against the frozen Hash baseline.")
        if report["qualityGate"].get("thresholds") != artifacts["gate"]:
            raise ValueError("M1 report does not embed the committed quality gate.")
        expected_policy_artifacts = {
            "qualityGateSha256": artifacts["fingerprints"]["qualityGate"]["sha256"],
            "baselineReportSha256": artifacts["fingerprints"]["baselineManifest"]["sha256"],
        }
        if run.get("policyArtifacts") != expected_policy_artifacts:
            raise ValueError("M1 report does not bind the committed baseline and gate SHA-256.")
        if int(run.get("embeddingFallbackCount") or 0):
            raise ValueError("M1 selection rejects embedding fallback.")

        config = run["resolvedConfig"]
        _validate_config_fingerprint(run, config)
        selected = _validate_embedding_profile(config, report)
        _validate_frozen_configuration(config, artifacts["baseline"], selected)
        _validate_result_rows(report, artifacts["caseLanguages"])
        _validate_summary_matches_results(report)
        index = report["index"]
        if (
            index.get("lifecycleState") != "complete"
            or index.get("configVerified") is not True
            or int(index.get("pointCount") or 0) != 145_000
            or int(index.get("vectorDimensions") or 0) != 1_024
        ):
            raise ValueError("M1 selection requires a complete verified 145,000-point 1024d index.")
        controls.append(normalized_dev_control(config, include_collection=False))

    reference_control = controls[0]
    if any(control != reference_control for control in controls[1:]):
        raise ValueError("M1 reports use different normalized Dev controls or Qdrant Server endpoints.")
    return controls


def _validate_config_fingerprint(run: dict[str, Any], config: dict[str, Any]) -> None:
    if run.get("configFingerprint") != _fingerprint(config):
        raise ValueError("M1 report resolved config fingerprint is invalid.")
    legacy_control = {
        "retrieval": config["retrieval"],
        "qdrant": {
            key: value
            for key, value in config["qdrant"].items()
            if key not in {"collection", "endpointFingerprint"}
        },
        "features": config["features"],
        "eval": config["eval"],
        "embeddingDimensions": config["embedding"]["dimensions"],
        "embeddingRuntime": {
            key: value
            for key, value in config["embedding"]["runtime"].items()
            if key not in {"providerBatchLimit", "effectiveBatchSize"}
        },
    }
    if config.get("experimentControlFingerprint") != _fingerprint(legacy_control):
        raise ValueError("M1 report experiment control fingerprint is invalid.")


def _validate_embedding_profile(
    config: dict[str, Any],
    report: dict[str, Any],
) -> EmbeddingProfile:
    embedding = config["embedding"]
    profile_id = str(embedding.get("profileId") or "")
    selected = PROFILES[profile_id]
    expected_identity = EmbeddingMetadata(
        provider=selected.provider,
        model=selected.model,
        dimensions=selected.dimensions,
        version=selected.version,
        query_mode=selected.query_mode,
        document_mode=selected.document_mode,
    ).identity
    expected = {
        "profileId": selected.profile_id,
        "provider": selected.provider,
        "model": selected.model,
        "dimensions": selected.dimensions,
        "version": selected.version,
        "metadataSource": "configured",
        "apiFlavor": selected.api_flavor,
        "queryMode": selected.query_mode,
        "documentMode": selected.document_mode,
        "identity": expected_identity,
        "priceUsdPerMillionTokens": selected.price_usd_per_million_tokens,
        "pricingSnapshotDate": "2026-08-31",
    }
    if any(embedding.get(key) != value for key, value in expected.items()):
        raise ValueError(f"M1 report has incomplete or drifted metadata for {profile_id}.")
    if not _is_sha256(embedding.get("endpointFingerprint")):
        raise ValueError(f"M1 report is missing a safe endpoint fingerprint for {profile_id}.")
    runtime = embedding.get("runtime") or {}
    configured_batch = int(runtime.get("configuredBatchSize") or 0)
    expected_runtime = {
        "providerBatchLimit": selected.provider_batch_limit,
        "effectiveBatchSize": min(configured_batch, selected.provider_batch_limit),
    }
    if configured_batch < 1 or any(runtime.get(key) != value for key, value in expected_runtime.items()):
        raise ValueError(f"M1 report has invalid provider batching metadata for {profile_id}.")
    for key in ("maxConcurrency", "maxBatchCharacters"):
        if not isinstance(runtime.get(key), int) or int(runtime[key]) < 1:
            raise ValueError(f"M1 report has invalid embedding runtime metadata for {profile_id}.")
    for key in ("maxRetries", "queryCacheSize"):
        if not isinstance(runtime.get(key), int) or int(runtime[key]) < 0:
            raise ValueError(f"M1 report has invalid embedding runtime metadata for {profile_id}.")
    _finite_positive(runtime.get("timeoutSeconds"), f"{profile_id} timeoutSeconds")
    _finite_nonnegative(runtime.get("queryCacheTtlSeconds"), f"{profile_id} queryCacheTtlSeconds")
    cap = _finite_positive(embedding.get("maxProviderCostUsd"), "provider cost cap")
    if cap > selected.max_cost_usd:
        raise ValueError(f"M1 report exceeds the frozen cost cap for {profile_id}.")
    expected_tokens = int(cap / selected.price_usd_per_million_tokens * 1_000_000)
    if int(embedding.get("maxTotalTokens") or 0) != expected_tokens:
        raise ValueError(f"M1 report token budget does not match its cost cap for {profile_id}.")

    usage = report.get("providerUsage") or {}
    total_tokens = int(usage.get("total_tokens") or 0)
    if total_tokens <= 0:
        raise ValueError(f"M1 report has no provider-reported token usage for {profile_id}.")
    estimated_cost = _finite_nonnegative(usage.get("estimatedCostUsd"), "estimated cost")
    expected_cost = total_tokens / 1_000_000 * selected.price_usd_per_million_tokens
    if not math.isclose(estimated_cost, expected_cost, abs_tol=1e-6):
        raise ValueError(f"M1 report cost is inconsistent with provider tokens for {profile_id}.")
    if (
        usage.get("priceUsdPerMillionTokens") != selected.price_usd_per_million_tokens
        or float(usage.get("hardCostCapUsd") or 0.0) != cap
        or estimated_cost > cap + 1e-6
    ):
        raise ValueError(f"M1 report provider usage violates the frozen profile for {profile_id}.")
    return selected


def _validate_frozen_configuration(
    config: dict[str, Any],
    baseline: dict[str, Any],
    selected: EmbeddingProfile,
) -> None:
    frozen = baseline.get("configuration") or {}
    retrieval = config.get("retrieval") or {}
    expected_retrieval = {
        "version": frozen.get("retrievalVersion"),
        "candidateLimit": frozen.get("candidateLimit"),
        "discoveryPoolSize": frozen.get("discoveryPoolSize"),
        "mode": frozen.get("candidateRetrieval"),
        "queryExpansion": frozen.get("queryExpansion"),
    }
    if any(retrieval.get(key) != value for key, value in expected_retrieval.items()):
        raise ValueError("M1 report retrieval configuration drifted from the frozen M0 control.")
    if not retrieval.get("indexBuildVersion") or not _is_sha256(retrieval.get("indexBuildSourceFingerprint")):
        raise ValueError("M1 report is missing its index build provenance.")
    expected_features = {
        "queryRewriteProvider": "disabled",
        "globalRetrievalMode": frozen.get("candidateRetrieval"),
        "rerankerProvider": frozen.get("reranker"),
    }
    if config.get("features") != expected_features:
        raise ValueError("M1 report feature configuration drifted from the frozen control.")
    evaluation = config.get("eval") or {}
    if (
        evaluation.get("split") != "dev"
        or evaluation.get("warmupCases") != frozen.get("warmupCases")
        or evaluation.get("concurrency") != frozen.get("concurrency")
        or evaluation.get("latencyMode") != "outer-wall-clock-sequential"
    ):
        raise ValueError("M1 report evaluation configuration drifted from the frozen control.")
    qdrant = config.get("qdrant") or {}
    if (
        qdrant.get("collection") != selected.collection
        or qdrant.get("locationKind") != "remote"
        or not _is_sha256(qdrant.get("endpointFingerprint"))
        or not isinstance(qdrant.get("reuseIndex"), bool)
    ):
        raise ValueError("M1 report Qdrant configuration is incomplete or drifted.")


def _validate_result_rows(report: dict[str, Any], case_languages: dict[str, str]) -> None:
    results = report.get("results") or []
    result_ids = [str(row.get("id") or "") for row in results]
    if len(results) != 80 or len(result_ids) != len(set(result_ids)):
        raise ValueError("M1 selection requires 80 unique result rows.")
    if set(result_ids) != set(case_languages):
        raise ValueError("M1 result IDs do not match the complete committed Dev case set.")
    for row in results:
        case_id = str(row["id"])
        if row.get("language") != case_languages[case_id]:
            raise ValueError(f"M1 result language does not match the Dev suite for {case_id}.")
        _finite_rate((row.get("metrics") or {}).get("ndcgAt10"), f"{case_id} nDCG@10")
        _finite_rate((row.get("metrics") or {}).get("mrrAt10"), f"{case_id} MRR@10")


def _validate_summary_matches_results(report: dict[str, Any]) -> None:
    computed = _recomputed_quality(report)
    summary = report.get("summary") or {}
    checks = {
        "overall nDCG@10": (
            (summary.get("overall") or {}).get("ndcgAt10"),
            computed["overallNdcgAt10"],
        ),
        "overall MRR@10": (
            (summary.get("overall") or {}).get("mrrAt10"),
            computed["overallMrrAt10"],
        ),
    }
    for language in ("en", "zh", "mixed"):
        checks[f"{language} nDCG@10"] = (
            ((summary.get("byLanguage") or {}).get(language) or {}).get("ndcgAt10"),
            computed["byLanguage"][language]["ndcgAt10"],
        )
        checks[f"{language} MRR@10"] = (
            ((summary.get("byLanguage") or {}).get(language) or {}).get("mrrAt10"),
            computed["byLanguage"][language]["mrrAt10"],
        )
    for label, (reported, actual) in checks.items():
        value = _finite_rate(reported, f"reported {label}")
        if not math.isclose(value, actual, abs_tol=SUMMARY_TOLERANCE):
            raise ValueError(f"M1 report summary does not match result rows for {label}.")


def normalized_dev_control(
    config: dict[str, Any],
    *,
    include_collection: bool,
) -> dict[str, Any]:
    """Normalize Dev/test config while excluding split and build-vs-reuse state."""

    qdrant_keys = ("locationKind", "endpointFingerprint")
    qdrant = {key: config["qdrant"][key] for key in qdrant_keys}
    if include_collection:
        qdrant["collection"] = config["qdrant"]["collection"]
    evaluation = config["eval"]
    return {
        "retrieval": config["retrieval"],
        "features": config["features"],
        "eval": {
            "warmupCases": evaluation["warmupCases"],
            "concurrency": evaluation["concurrency"],
            "latencyMode": evaluation["latencyMode"],
        },
        "embeddingRuntime": {
            key: value
            for key, value in config["embedding"]["runtime"].items()
            if key not in {"providerBatchLimit", "effectiveBatchSize"}
        },
        "qdrant": qdrant,
    }


def _score_report(
    report: dict[str, Any],
    path: Path,
    baseline: dict[str, float],
) -> dict[str, Any]:
    embedding = report["run"]["resolvedConfig"]["embedding"]
    quality = _recomputed_quality(report)
    bilingual_ndcg = quality["bilingualNdcgAt10"]
    bilingual_mrr = quality["bilingualMrrAt10"]
    ndcg_gain = bilingual_ndcg - baseline["bilingualNdcgAt10"]
    mrr_gain = bilingual_mrr - baseline["bilingualMrrAt10"]
    embedding_p95 = _finite_nonnegative(
        report["summary"]["latencyMs"]["embedding"]["p95"],
        "embedding P95",
    )
    estimated_cost = _finite_nonnegative(
        report["providerUsage"]["estimatedCostUsd"],
        "estimated cost",
    )
    return {
        "profileId": embedding["profileId"],
        "report": path.name,
        "reportSha256": _sha256_file(path),
        "bilingualNdcgAt10": bilingual_ndcg,
        "bilingualMrrAt10": bilingual_mrr,
        "overallNdcgAt10": quality["overallNdcgAt10"],
        "overallMrrAt10": quality["overallMrrAt10"],
        "bilingualNdcgGainVsHash": ndcg_gain,
        "bilingualMrrGainVsHash": mrr_gain,
        "meetsHashImprovementGate": (
            ndcg_gain >= MIN_BILINGUAL_GAIN_VS_HASH - SUMMARY_TOLERANCE
            and mrr_gain >= MIN_BILINGUAL_GAIN_VS_HASH - SUMMARY_TOLERANCE
        ),
        "estimatedCostUsd": estimated_cost,
        "embeddingP95Ms": embedding_p95,
    }


def _recomputed_quality(report: dict[str, Any]) -> dict[str, Any]:
    results = report["results"]
    by_language: dict[str, dict[str, float]] = {}
    for language in ("en", "zh", "mixed"):
        rows = [row for row in results if row["language"] == language]
        by_language[language] = {
            metric: statistics.fmean(float(row["metrics"][metric]) for row in rows)
            for metric in ("ndcgAt10", "mrrAt10")
        }
    bilingual = [row for row in results if row["language"] in {"zh", "mixed"}]
    return {
        "byLanguage": by_language,
        "overallNdcgAt10": statistics.fmean(float(row["metrics"]["ndcgAt10"]) for row in results),
        "overallMrrAt10": statistics.fmean(float(row["metrics"]["mrrAt10"]) for row in results),
        "bilingualNdcgAt10": statistics.fmean(float(row["metrics"]["ndcgAt10"]) for row in bilingual),
        "bilingualMrrAt10": statistics.fmean(float(row["metrics"]["mrrAt10"]) for row in bilingual),
    }


def _paired_bootstrap(winner: dict, other: dict) -> dict[str, float]:
    winner_cases = {
        row["id"]: float(row["metrics"]["ndcgAt10"])
        for row in winner["results"]
        if row["language"] in {"zh", "mixed"}
    }
    other_cases = {
        row["id"]: float(row["metrics"]["ndcgAt10"])
        for row in other["results"]
        if row["language"] in {"zh", "mixed"}
    }
    if winner_cases.keys() != other_cases.keys():
        raise ValueError("Bilingual cases differ across M1 reports.")
    deltas = [winner_cases[key] - other_cases[key] for key in sorted(winner_cases)]
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(sum(rng.choice(deltas) for _ in deltas) / len(deltas) for _ in range(BOOTSTRAP_SAMPLES))
    lower = means[int(0.025 * BOOTSTRAP_SAMPLES)]
    upper = means[int(0.975 * BOOTSTRAP_SAMPLES) - 1]
    return {
        "meanNdcgAt10Delta": sum(deltas) / len(deltas),
        "ci95Lower": lower,
        "ci95Upper": upper,
    }


def _finite_rate(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite value between zero and one.") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise ValueError(f"{label} must be a finite value between zero and one.")
    return parsed


def _finite_nonnegative(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative value.") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{label} must be a finite non-negative value.")
    return parsed


def _finite_positive(value: Any, label: str) -> float:
    parsed = _finite_nonnegative(value, label)
    if parsed <= 0:
        raise ValueError(f"{label} must be positive.")
    return parsed


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _load_report(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid report: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_json_atomic(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen winner manifest: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the frozen M1 embedding winner policy.")
    parser.add_argument("reports", nargs=3, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare([path.resolve() for path in args.reports])
    _write_json_atomic(args.output.resolve(), result)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
