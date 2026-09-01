from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from app.rag.embeddings import EmbeddingMetadata
from evals.rag_v2.compare_m1 import (
    BILINGUAL_TIE_BAND,
    EXPECTED_PROFILES,
    MIN_BILINGUAL_GAIN_VS_HASH,
    POLICY_VERSION,
    _paired_bootstrap,
    _write_json_atomic,
    compare,
)
from evals.rag_v2.embedding_profiles import PROFILES

EVAL_DIRECTORY = Path(__file__).parents[1] / "evals" / "rag_v2"
DEV_SUITE = json.loads((EVAL_DIRECTORY / "cases.dev.json").read_text(encoding="utf-8"))
QUALITY_GATE = json.loads((EVAL_DIRECTORY / "quality_gate.json").read_text(encoding="utf-8"))
BASELINE = json.loads((EVAL_DIRECTORY / "baseline.hash64.local.json").read_text(encoding="utf-8"))
PROFILE_IDS = (
    "openai-small-1024",
    "openai-large-1024",
    "qwen37-1024",
)


def _canonical_fingerprint(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _refresh_fingerprints(report: dict[str, Any]) -> None:
    config = report["run"]["resolvedConfig"]
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
    config["experimentControlFingerprint"] = _canonical_fingerprint(legacy_control)
    report["run"]["configFingerprint"] = _canonical_fingerprint(config)


def _report(
    profile_id: str,
    *,
    bilingual_ndcg: float = 0.80,
    overall_ndcg: float = 0.80,
    bilingual_mrr: float = 0.94,
    estimated_cost_usd: float = 0.2,
    embedding_p95_ms: float = 100.0,
) -> dict[str, Any]:
    selected = PROFILES[profile_id]
    english_ndcg = overall_ndcg * 2 - bilingual_ndcg
    if not 0 <= english_ndcg <= 1:
        raise ValueError("Fixture overall/bilingual scores imply an invalid English score.")
    english_mrr = 0.92
    results = []
    for case in DEV_SUITE["cases"]:
        bilingual = case["language"] in {"zh", "mixed"}
        results.append(
            {
                "id": case["id"],
                "language": case["language"],
                "metrics": {
                    "ndcgAt10": bilingual_ndcg if bilingual else english_ndcg,
                    "mrrAt10": bilingual_mrr if bilingual else english_mrr,
                },
            }
        )
    by_language = {
        language: {
            metric: sum(row["metrics"][metric] for row in results if row["language"] == language)
            / sum(row["language"] == language for row in results)
            for metric in ("ndcgAt10", "mrrAt10")
        }
        for language in ("en", "zh", "mixed")
    }
    identity = EmbeddingMetadata(
        provider=selected.provider,
        model=selected.model,
        dimensions=selected.dimensions,
        version=selected.version,
        query_mode=selected.query_mode,
        document_mode=selected.document_mode,
    ).identity
    embedding = {
        "provider": selected.provider,
        "model": selected.model,
        "dimensions": selected.dimensions,
        "version": selected.version,
        "metadataSource": "configured",
        "endpointFingerprint": "a" * 64,
        "profileId": selected.profile_id,
        "apiFlavor": selected.api_flavor,
        "queryMode": selected.query_mode,
        "documentMode": selected.document_mode,
        "identity": identity,
        "priceUsdPerMillionTokens": selected.price_usd_per_million_tokens,
        "maxProviderCostUsd": selected.max_cost_usd,
        "maxTotalTokens": selected.max_total_tokens,
        "pricingSnapshotDate": "2026-08-31",
        "runtime": {
            "configuredBatchSize": 64,
            "providerBatchLimit": selected.provider_batch_limit,
            "effectiveBatchSize": min(64, selected.provider_batch_limit),
            "maxConcurrency": 2,
            "timeoutSeconds": 30.0,
            "maxRetries": 4,
            "maxBatchCharacters": 250_000,
            "queryCacheSize": 512,
            "queryCacheTtlSeconds": 900.0,
        },
    }
    frozen = BASELINE["configuration"]
    resolved_config = {
        "retrieval": {
            "version": frozen["retrievalVersion"],
            "candidateLimit": frozen["candidateLimit"],
            "discoveryPoolSize": frozen["discoveryPoolSize"],
            "mode": frozen["candidateRetrieval"],
            "queryExpansion": frozen["queryExpansion"],
            "indexBuildVersion": "rag-document-transform-v3-m1",
            "indexBuildSourceFingerprint": "b" * 64,
        },
        "embedding": embedding,
        "qdrant": {
            "collection": selected.collection,
            "locationKind": "remote",
            "reuseIndex": False,
            "endpointFingerprint": "c" * 64,
        },
        "features": {
            "queryRewriteProvider": "disabled",
            "globalRetrievalMode": frozen["candidateRetrieval"],
            "rerankerProvider": frozen["reranker"],
        },
        "eval": {
            "split": "dev",
            "warmupCases": frozen["warmupCases"],
            "concurrency": frozen["concurrency"],
            "latencyMode": "outer-wall-clock-sequential",
        },
    }
    total_tokens = max(
        1,
        round(estimated_cost_usd / selected.price_usd_per_million_tokens * 1_000_000),
    )
    report = {
        "suite": {
            "split": "dev",
            "caseCount": 80,
            "caseSha256": DEV_SUITE["caseSha256"],
            "suiteContractSha256": DEV_SUITE["suiteContractSha256"],
            "datasetSha256": DEV_SUITE["datasetSha256"],
            "dataVersion": DEV_SUITE["dataVersion"],
        },
        "run": {
            "partial": False,
            "evaluatedCases": 80,
            "embeddingFallbackCount": 0,
            "scopedSource": {"sha256": "d" * 64},
            "resolvedConfig": resolved_config,
            "policyArtifacts": {
                "qualityGateSha256": hashlib.sha256(
                    (EVAL_DIRECTORY / "quality_gate.json").read_bytes()
                ).hexdigest(),
                "baselineReportSha256": hashlib.sha256(
                    (EVAL_DIRECTORY / "baseline.hash64.local.json").read_bytes()
                ).hexdigest(),
            },
        },
        "qualityGate": {
            "passed": True,
            "failures": [],
            "warnings": [],
            "relativeStatus": "evaluated",
            "thresholds": copy.deepcopy(QUALITY_GATE),
        },
        "index": {
            "lifecycleState": "complete",
            "configVerified": True,
            "pointCount": 145_000,
            "vectorDimensions": 1_024,
        },
        "summary": {
            "byLanguage": by_language,
            "overall": {
                "ndcgAt10": sum(row["metrics"]["ndcgAt10"] for row in results) / 80,
                "mrrAt10": sum(row["metrics"]["mrrAt10"] for row in results) / 80,
            },
            "latencyMs": {"embedding": {"p95": embedding_p95_ms}},
        },
        "providerUsage": {
            "total_tokens": total_tokens,
            "priceUsdPerMillionTokens": selected.price_usd_per_million_tokens,
            "estimatedCostUsd": estimated_cost_usd,
            "hardCostCapUsd": selected.max_cost_usd,
        },
        "results": results,
    }
    _refresh_fingerprints(report)
    return report


def _write_reports(tmp_path: Path, reports: list[dict[str, Any]]) -> list[Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, report in enumerate(reports):
        profile_id = report["run"]["resolvedConfig"]["embedding"]["profileId"]
        path = tmp_path / f"{index}-{profile_id}.json"
        path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        paths.append(path)
    return paths


def test_compare_accepts_exactly_three_complete_comparable_profiles(tmp_path: Path):
    reports = [
        _report("openai-small-1024", bilingual_ndcg=0.79),
        _report("openai-large-1024", bilingual_ndcg=0.81),
        _report("qwen37-1024", bilingual_ndcg=0.82),
    ]
    paths = _write_reports(tmp_path, reports)

    result = compare(paths)

    assert result["policyVersion"] == POLICY_VERSION
    assert {row["profileId"] for row in result["candidates"]} == EXPECTED_PROFILES
    assert result["winnerProfileId"] == "qwen37-1024"
    assert result["winnerEmbedding"]["dimensions"] == 1_024
    assert result["comparisonControl"]["qdrant"]["endpointFingerprint"] == "c" * 64
    assert "collection" not in result["comparisonControl"]["qdrant"]
    assert result["winnerDevControl"]["qdrant"]["collection"] == PROFILES["qwen37-1024"].collection
    assert len(result["winnerDevControlFingerprint"]) == 64
    assert result["frozenArtifacts"]["baselineManifest"]["sha256"]
    assert result["frozenArtifacts"]["qualityGate"]["sha256"]
    assert set(result["devReports"]) == set(PROFILE_IDS)
    assert all(len(value["sha256"]) == 64 for value in result["devReports"].values())


def test_compare_rejects_missing_or_unexpected_profile_sets(tmp_path: Path):
    complete = [_report(profile_id) for profile_id in PROFILE_IDS]
    with pytest.raises(ValueError, match="exactly three Dev reports"):
        compare(_write_reports(tmp_path / "missing", complete[:2]))

    unexpected = copy.deepcopy(complete)
    unexpected[-1]["run"]["resolvedConfig"]["embedding"]["profileId"] = "other-1024"
    with pytest.raises(ValueError, match="must cover exactly"):
        compare(_write_reports(tmp_path / "unexpected", unexpected))


def test_compare_validates_complete_frozen_result_ids(tmp_path: Path):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[1]["results"].pop()

    with pytest.raises(ValueError, match="80 unique result rows"):
        compare(_write_reports(tmp_path, reports))

    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[1]["results"][0]["id"] = "invented-case"
    with pytest.raises(ValueError, match="complete committed Dev case set"):
        compare(_write_reports(tmp_path / "ids", reports))


def _change_control(report: dict[str, Any]) -> None:
    report["run"]["resolvedConfig"]["qdrant"]["endpointFingerprint"] = "e" * 64
    _refresh_fingerprints(report)


def _change_source(report: dict[str, Any]) -> None:
    report["run"]["scopedSource"]["sha256"] = "e" * 64


def _change_suite(report: dict[str, Any]) -> None:
    report["suite"]["caseSha256"] = "e" * 64


def _mark_partial(report: dict[str, Any]) -> None:
    report["run"]["partial"] = True


def _add_fallback(report: dict[str, Any]) -> None:
    report["run"]["embeddingFallbackCount"] = 1


def _invalidate_index(report: dict[str, Any]) -> None:
    report["index"]["pointCount"] = 144_999


def _fail_quality(report: dict[str, Any]) -> None:
    report["qualityGate"]["passed"] = False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_change_control, "different normalized Dev controls"),
        (_change_source, "different scoped source versions"),
        (_change_suite, "committed frozen Dev suite"),
        (_mark_partial, "partial Dev reports"),
        (_add_fallback, "embedding fallback"),
        (_invalidate_index, "complete verified 145,000-point 1024d index"),
        (_fail_quality, "failed its quality gate"),
    ],
    ids=("control", "source", "suite", "partial", "fallback", "index", "quality"),
)
def test_compare_rejects_incomparable_or_ineligible_candidates(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    mutation(reports[1])

    with pytest.raises(ValueError, match=message):
        compare(_write_reports(tmp_path, reports))


def test_compare_requires_committed_gate_and_frozen_baseline_evaluation(tmp_path: Path):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[0]["qualityGate"]["relativeStatus"] = "not-requested"
    with pytest.raises(ValueError, match="frozen Hash baseline"):
        compare(_write_reports(tmp_path / "baseline", reports))

    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[0]["qualityGate"]["thresholds"]["absolute"]["minimums"]["overall.evidenceCoverage"] = 0.0
    with pytest.raises(ValueError, match="committed quality gate"):
        compare(_write_reports(tmp_path / "gate", reports))

    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[0]["run"]["policyArtifacts"]["baselineReportSha256"] = "e" * 64
    with pytest.raises(ValueError, match="committed baseline and gate SHA-256"):
        compare(_write_reports(tmp_path / "artifact-sha", reports))


def test_compare_rejects_drifted_embedding_metadata_and_provider_cost(tmp_path: Path):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[0]["run"]["resolvedConfig"]["embedding"].pop("identity")
    _refresh_fingerprints(reports[0])
    with pytest.raises(ValueError, match="incomplete or drifted metadata"):
        compare(_write_reports(tmp_path / "metadata", reports))

    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[0]["providerUsage"]["estimatedCostUsd"] = 0.01
    with pytest.raises(ValueError, match="cost is inconsistent"):
        compare(_write_reports(tmp_path / "cost", reports))


def test_compare_recomputes_scores_and_rejects_stale_summary(tmp_path: Path):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[2]["summary"]["byLanguage"]["zh"]["ndcgAt10"] += 0.1

    with pytest.raises(ValueError, match="summary does not match result rows"):
        compare(_write_reports(tmp_path, reports))


def test_hash_improvement_gate_excludes_regressed_candidates_and_can_block_m1(tmp_path: Path):
    baseline_dev = BASELINE["splits"]["dev"]
    baseline_ndcg = (
        baseline_dev["languageNdcgAt10"]["zh"] * 30 + baseline_dev["languageNdcgAt10"]["mixed"] * 10
    ) / 40
    baseline_mrr = (
        baseline_dev["languageMrrAt10"]["zh"] * 30 + baseline_dev["languageMrrAt10"]["mixed"] * 10
    ) / 40
    assert MIN_BILINGUAL_GAIN_VS_HASH == 0.005

    reports = [
        _report(
            profile_id,
            bilingual_ndcg=baseline_ndcg + 0.004,
            bilingual_mrr=baseline_mrr + 0.004,
        )
        for profile_id in PROFILE_IDS
    ]
    with pytest.raises(ValueError, match="No M1 candidate improves both"):
        compare(_write_reports(tmp_path / "blocked", reports))

    reports = [
        _report(
            "openai-small-1024",
            bilingual_ndcg=baseline_ndcg + 0.006,
            bilingual_mrr=baseline_mrr + 0.006,
            overall_ndcg=0.79,
        ),
        _report(
            "openai-large-1024",
            bilingual_ndcg=baseline_ndcg + 0.004,
            bilingual_mrr=baseline_mrr + 0.02,
            overall_ndcg=0.85,
        ),
        _report(
            "qwen37-1024",
            bilingual_ndcg=baseline_ndcg + 0.02,
            bilingual_mrr=baseline_mrr + 0.004,
            overall_ndcg=0.85,
        ),
    ]
    result = compare(_write_reports(tmp_path / "one-eligible", reports))
    assert result["winnerProfileId"] == "openai-small-1024"
    assert sum(row["meetsHashImprovementGate"] for row in result["candidates"]) == 1


def test_half_percentage_point_tie_band_is_inclusive_and_excludes_outsiders(
    tmp_path: Path,
):
    reports = [
        _report(
            "qwen37-1024",
            bilingual_ndcg=0.8000,
            overall_ndcg=0.80,
        ),
        _report(
            "openai-large-1024",
            bilingual_ndcg=0.7950,
            overall_ndcg=0.82,
        ),
        _report(
            "openai-small-1024",
            bilingual_ndcg=0.7949,
            overall_ndcg=0.84,
        ),
    ]

    result = compare(_write_reports(tmp_path, reports))

    assert BILINGUAL_TIE_BAND == 0.005
    assert result["policy"]["tieBand"] == 0.005
    assert result["winnerProfileId"] == "openai-large-1024"


def test_exact_ties_have_a_deterministic_profile_id_tie_break(tmp_path: Path):
    reports = [
        _report(
            profile_id,
            bilingual_ndcg=0.8,
            overall_ndcg=0.8,
            bilingual_mrr=0.94,
            estimated_cost_usd=0.2,
            embedding_p95_ms=100.0,
        )
        for profile_id in PROFILE_IDS
    ]
    paths = _write_reports(tmp_path, reports)

    winners = {compare(list(order))["winnerProfileId"] for order in permutations(paths)}

    assert winners == {"openai-large-1024"}


def test_build_vs_reuse_is_excluded_from_normalized_control(tmp_path: Path):
    reports = [_report(profile_id) for profile_id in PROFILE_IDS]
    reports[1]["run"]["resolvedConfig"]["qdrant"]["reuseIndex"] = True
    _refresh_fingerprints(reports[1])

    result = compare(_write_reports(tmp_path, reports))

    assert "reuseIndex" not in result["comparisonControl"]["qdrant"]
    assert "reuseIndex" not in result["winnerDevControl"]["qdrant"]


def test_paired_bootstrap_is_seeded_and_order_independent():
    winner = _report("qwen37-1024")
    other = _report("openai-small-1024")
    bilingual_winner = [row for row in winner["results"] if row["language"] in {"zh", "mixed"}]
    bilingual_other = [row for row in other["results"] if row["language"] in {"zh", "mixed"}]
    for index, (winner_row, other_row) in enumerate(zip(bilingual_winner, bilingual_other, strict=True)):
        winner_row["metrics"]["ndcgAt10"] = 0.7
        other_row["metrics"]["ndcgAt10"] = 0.6 if index % 2 == 0 else 0.72

    first = _paired_bootstrap(winner, other)
    other["results"].reverse()
    second = _paired_bootstrap(winner, other)

    assert first == second
    assert first["meanNdcgAt10Delta"] == pytest.approx(0.04)
    assert first["ci95Lower"] < first["meanNdcgAt10Delta"] < first["ci95Upper"]


def test_winner_manifest_is_written_once_and_never_overwritten(tmp_path: Path):
    output = tmp_path / "winner.json"
    original = {"winnerProfileId": "qwen37-1024"}
    replacement = {"winnerProfileId": "openai-large-1024"}

    _write_json_atomic(output, original)
    with pytest.raises(FileExistsError, match="Refusing to overwrite frozen winner manifest"):
        _write_json_atomic(output, replacement)

    assert json.loads(output.read_text(encoding="utf-8")) == original
    assert not output.with_suffix(".json.tmp").exists()
