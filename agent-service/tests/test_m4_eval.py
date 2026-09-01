from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from evals.rag_v2.build_m3_cases import (
    M3_JUDGMENT_POLICY_VERSION,
    M3_SUITE_NAME,
    m3_suite_contract_sha256,
    rewrite_config_fingerprint,
)
from evals.rag_v2.build_m4_cases import (
    M4_CANDIDATE_UNIVERSE_FILENAME,
    M4_SELECTION_LEAKAGE_WARNING,
    M4_SUITE_NAME,
    build_m4_dev_suite,
    capture_m4_candidate_universe,
    m4_candidate_universe_sha256,
    m4_experiment_fingerprint,
    m4_suite_contract_sha256,
    reranker_config_fingerprint,
    validate_frozen_m3_dev_source_suite,
    write_m4_artifacts,
)
from evals.rag_v2.compare_m4 import (
    DEFAULT_GATE,
    _summarize_m4_results,
    compare,
    paired_bootstrap_mean_ci,
    write_comparison,
)
from evals.rag_v2.contract import sha256_json
from evals.rag_v2.metrics import rounded
from evals.rag_v2.run_eval import _reranker_case_usage, _retrieval_trace, build_parser


def test_m4_schema_v5_labels_complete_shared_pool_and_freezes_inputs(tmp_path):
    source = _source_suite()
    capture = _capture_report(source)
    universe = capture_m4_candidate_universe(
        source_suite=source,
        capture_report=capture,
        trusted_source_suite=source,
    )
    suite = build_m4_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )

    assert suite["schemaVersion"] == 5
    assert suite["suite"] == M4_SUITE_NAME
    assert suite["evaluationDesign"]["armCandidatePoolPolicy"] == "identical-frozen-replay"
    assert suite["judgmentContract"]["preRerankCandidatePairs"] == 6
    assert suite["judgmentContract"]["candidateLimit"] == 30
    assert suite["judgmentContract"]["finalCandidateLimit"] == 10
    assert suite["judgmentContract"]["selectionLeakageWarning"] == M4_SELECTION_LEAKAGE_WARNING
    assert suite["caseSha256"] == sha256_json(suite["cases"])
    assert suite["suiteContractSha256"] == m4_suite_contract_sha256(suite)
    assert universe["fixtureSha256"] == m4_candidate_universe_sha256(universe)
    assert universe["candidatePoolContractSha256"] == sha256_json(universe["cases"])
    for case in suite["cases"]:
        assert {item["externalId"] for item in case["judgments"]} == {
            "merchant:low",
            "merchant:high",
            "merchant:medium",
        }
        assert all(
            item["judgmentOrigins"] == ["m4-shared-pre-rerank-top-30"]
            for item in case["judgments"]
        )
        assert case["metadata"]["judgmentCompleteness"] == (
            "complete-for-frozen-m4-pre-rerank-top-30-pool"
        )
        assert case["metadata"]["rerankerInputFingerprint"] == "a" * 64


def test_m4_capture_rejects_non_m3_source_and_pool_or_input_tampering(tmp_path):
    source = _source_suite()
    forbidden = deepcopy(source)
    forbidden["schemaVersion"] = 3
    with pytest.raises(ValueError, match="schema-v4 M3 Dev"):
        validate_frozen_m3_dev_source_suite(
            forbidden,
            trusted_source_suite=forbidden,
        )

    capture = _capture_report(source)
    capture["results"][0]["retrievalTrace"]["preRerankPoolFingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="fingerprint does not match IDs"):
        capture_m4_candidate_universe(
            source_suite=source,
            capture_report=capture,
            trusted_source_suite=source,
        )

    capture = _capture_report(source)
    capture["results"][0]["retrievalTrace"]["rerankerInputFingerprint"] = "bad"
    with pytest.raises(ValueError, match="input fingerprint"):
        capture_m4_candidate_universe(
            source_suite=source,
            capture_report=capture,
            trusted_source_suite=source,
        )

    capture = _capture_report(source)
    universe = capture_m4_candidate_universe(
        source_suite=source,
        capture_report=capture,
        trusted_source_suite=source,
    )
    universe["cases"][0]["preRerankCandidateExternalIds"].append("merchant:extra")
    with pytest.raises(ValueError, match="fixture SHA"):
        build_m4_dev_suite(
            _write_dataset(tmp_path / "data"),
            source,
            universe,
            trusted_source_suite=source,
        )


def test_m4_compare_passes_quality_with_latency_waiver_and_deterministic_ci(tmp_path):
    source = _source_suite()
    capture = _capture_report(source)
    universe = capture_m4_candidate_universe(
        source_suite=source,
        capture_report=capture,
        trusted_source_suite=source,
    )
    suite = build_m4_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    control, treatment = _comparison_reports(suite, capture)
    control_path, treatment_path = _write_reports(tmp_path, control, treatment)

    result = compare(control_path, treatment_path)

    assert result["passed"] is True
    assert result["promotionStatus"] == "quality-accepted-under-latency-waiver"
    assert result["deltas"]["overall.ndcgAt5"] == 0.01
    assert result["pairedBootstrap"]["observedMeanDelta"] == 0.01
    assert result["pairedBootstrap"]["lower"] == 0.01
    assert result["requestDeltas"]["requestCounts.rerankerProviderNetworkRequests"] == 2
    assert result["costs"]["treatment"]["estimatedCostUsd"] == 0.002
    assert result["latencyObservation"]["gating"] is False
    assert result["latencyObservation"]["total"]["ratio"] == 5.0

    ci = paired_bootstrap_mean_ci(
        [0.2, -0.1, 0.3], confidence=0.95, resamples=1000, seed=7
    )
    assert ci == paired_bootstrap_mean_ci(
        [0.2, -0.1, 0.3], confidence=0.95, resamples=1000, seed=7
    )


def test_m4_compare_rejects_pool_drift_fallback_and_failed_bootstrap_gate(tmp_path):
    source = _source_suite()
    capture = _capture_report(source)
    universe = capture_m4_candidate_universe(
        source_suite=source,
        capture_report=capture,
        trusted_source_suite=source,
    )
    suite = build_m4_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    control, treatment = _comparison_reports(suite, capture)
    control_path, _ = _write_reports(tmp_path, control, treatment)

    drifted = deepcopy(treatment)
    drifted["results"][0]["retrievalTrace"]["rerankerInputFingerprint"] = "c" * 64
    drifted_path = tmp_path / "drifted.json"
    drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen candidate/input pool"):
        compare(control_path, drifted_path)

    fallback = deepcopy(treatment)
    fallback["results"][0]["requests"]["rerankerFallback"] = True
    fallback["run"]["rerankerFallbackCount"] = 1
    fallback_path = tmp_path / "fallback.json"
    fallback_path.write_text(json.dumps(fallback), encoding="utf-8")
    with pytest.raises(ValueError, match="reject fallback"):
        compare(control_path, fallback_path)

    regressed = deepcopy(treatment)
    for row in regressed["results"]:
        row["metrics"]["ndcgAt5"] = 0.399
    regressed["summary"] = rounded(_summarize_m4_results(regressed["results"]))
    regressed_path = tmp_path / "regressed.json"
    regressed_path.write_text(json.dumps(regressed), encoding="utf-8")
    result = compare(control_path, regressed_path)
    assert result["passed"] is False
    assert any("overall.ndcgAt5" in failure for failure in result["failures"])
    assert any("paired bootstrap" in failure for failure in result["failures"])


def test_m4_artifacts_and_comparison_refuse_overwrite(tmp_path):
    source = _source_suite()
    capture = _capture_report(source)
    universe = capture_m4_candidate_universe(
        source_suite=source,
        capture_report=capture,
        trusted_source_suite=source,
    )
    suite = build_m4_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    adversarial = tmp_path / "adversarial.json"
    adversarial.write_text("{}\n", encoding="utf-8")
    output_directory = tmp_path / "frozen"
    paths = write_m4_artifacts(
        output_directory,
        suite=suite,
        candidate_universe=universe,
        adversarial_source=adversarial,
    )
    assert paths["candidateUniverse"].name == M4_CANDIDATE_UNIVERSE_FILENAME
    with pytest.raises(FileExistsError, match="overwrite"):
        write_m4_artifacts(
            output_directory,
            suite=suite,
            candidate_universe=universe,
            adversarial_source=adversarial,
        )

    comparison = tmp_path / "comparison.json"
    write_comparison(comparison, {"passed": True})
    with pytest.raises(FileExistsError):
        write_comparison(comparison, {"passed": False})


def test_m4_run_eval_cli_and_metadata_normalization_are_schema_v5_ready():
    args = build_parser().parse_args(["--m4-capture"])
    assert args.m4_capture is True
    assert args.reranker_provider == "heuristic-multi-signal"
    assert args.reranker_candidate_limit == 30

    pool = ["merchant:one", "merchant:two"]
    metadata = {
        "globalRetrievalEnabled": True,
        "preRerankCandidateExternalIds": pool,
        "preRerankPoolFingerprint": sha256_json(pool),
        "rerankerInputExternalIds": pool,
        "rerankerInputFingerprint": "a" * 64,
        "rerankerInputDocumentIds": {"1": ["review:1"]},
        "rerankerEnabled": True,
        "rerankerProvider": "qwen",
        "rerankerModel": "qwen3-rerank",
        "rerankerModelVersion": "m4-v1",
        "rerankerStatus": "applied",
        "rerankerCandidates": 2,
        "rerankerLatencyMs": 12.5,
        "rerankerNetworkRequests": 1,
        "rerankerTokens": 52,
        "rerankerEstimatedCostUsd": 0.00001,
        "rerankerRetries": 0,
        "rerankerFailures": 0,
        "rerankerFallback": False,
        "rerankerCacheHit": False,
        "rerankerCircuitState": "closed",
    }
    usage = _reranker_case_usage(metadata, enabled=True)
    trace = _retrieval_trace(metadata, structured_count=1, returned_count=2)
    assert usage == {
        "network_requests": 1,
        "total_tokens": 52,
        "retry_count": 0,
        "failure_count": 0,
        "cache_hits": 0,
        "estimated_cost_usd": 0.00001,
    }
    assert trace["preRerankCandidateExternalIds"] == pool
    assert trace["rerankerInputFingerprint"] == "a" * 64
    assert trace["rerankerNetworkRequests"] == 1

    changed_instruction = _config("qwen3-rerank")
    original_fingerprint = reranker_config_fingerprint(changed_instruction)
    changed_instruction["reranker"]["instructionSha256"] = "8" * 64
    assert reranker_config_fingerprint(changed_instruction) != original_fingerprint


def _source_suite() -> dict:
    cases = [
        _source_case("dev-en-001", "en", "semantic_alias_composition"),
        _source_case("dev-zh-001", "zh", "negation_exclusion"),
    ]
    suite = {
        "schemaVersion": 4,
        "suite": M3_SUITE_NAME,
        "split": "dev",
        "retrievalVersion": "p12-rag-v1",
        "generatorVersion": "m3-test",
        "labelPolicyVersion": "derived-merchant-attributes-v1",
        "labelSource": "deterministic-derived-merchant-attributes",
        "adjudicationStatus": "deterministic-bounded-union-not-human-adjudicated",
        "dataVersion": "fixture-v1",
        "datasetSha256": "d" * 64,
        "binaryRelevanceThreshold": 2,
        "allowedCitationSourceTypes": ["shop_review"],
        "indexedDocuments": 12,
        "caseCount": len(cases),
        "caseSha256": sha256_json(cases),
        "languageCounts": {"en": 1, "zh": 1},
        "scenarioCounts": {"negation_exclusion": 1, "semantic_alias_composition": 1},
        "evaluationDesign": {"holdout": "m3-dev-only", "m1PolicyHoldoutUsed": False},
        "splitIsolation": {"intentGroupOverlap": 0},
        "hardNegativeCoverage": {"declared": 0},
        "adversarialFixtureSha256": "e" * 64,
        "cases": cases,
        "judgmentContract": {
            "policyVersion": M3_JUDGMENT_POLICY_VERSION,
            "sourceSplit": "dev",
            "m1PolicyHoldoutUsed": False,
            "m1PolicyHoldoutForbidden": True,
        },
    }
    suite["suiteContractSha256"] = m3_suite_contract_sha256(suite)
    return suite


def _source_case(case_id: str, language: str, scenario: str) -> dict:
    return {
        "id": case_id,
        "split": "dev",
        "language": language,
        "scenario": scenario,
        "intentGroup": case_id,
        "query": f"query for {case_id}",
        "constraints": {},
        "preferenceTags": ["quiet", "vegan"],
        "hardConstraints": {
            "category": "Food & Dining",
            "neighborhood": "Midtown",
            "borough": "Manhattan",
            "businessStatus": "OPERATIONAL",
            "maxPricePerPersonCents": None,
            "requiredTags": [],
            "excludedTags": [],
            "openAt": None,
        },
        "judgments": [
            {
                "shopId": 1,
                "externalId": "merchant:high",
                "relevance": 3,
                "matchedPreferences": ["quiet", "vegan"],
                "hardConstraintViolations": [],
            }
        ],
        "forbiddenDocumentIds": [],
        "hardNegatives": [],
        "metadata": {},
    }


def _config(provider: str) -> dict:
    learned = provider != "heuristic-multi-signal"
    config = {
        "retrieval": {
            "mode": "global-hybrid",
            "candidateLimit": 10,
            "fusionPoolLimit": 30,
        },
        "embedding": {"identity": "1" * 64},
        "qdrant": {"collection": "fixture"},
        "features": {
            "globalRetrievalEnabled": True,
            "queryRewriteEnabled": True,
            "queryRewriteProvider": "openai",
            "rerankerProvider": provider,
            "rerankerEnabled": learned,
        },
        "eval": {"split": "dev"},
        "queryRewrite": {
            "enabled": True,
            "provider": "openai",
            "promptVersion": "m3-v1",
            "promptFingerprint": "2" * 64,
        },
        "reranker": {
            "enabled": learned,
            "provider": provider,
            "model": "fixture-model" if learned else "heuristic-multi-signal",
            "inputVersion": "merchant-rerank-text-v1",
            "inputBuilderFingerprint": "3" * 64,
            "instructionVersion": "m4-reranker-instruction-v1",
            "instructionSha256": "9" * 64,
            "topN": 30,
        },
    }
    config["features"]["queryRewriteConfigFingerprint"] = rewrite_config_fingerprint(config)
    return config


def _capture_report(source: dict) -> dict:
    config = _config("heuristic-multi-signal")
    source_snapshot = {
        "fileSha256": {"fixture.py": "4" * 64},
        "sha256": sha256_json({"fixture.py": "4" * 64}),
        "dirty": False,
    }
    run = {
        "git": {"sha": "5" * 40, "dirty": False},
        "scopedSource": source_snapshot,
        "runtimeEnvironment": {
            "pythonVersion": "3.13",
            "qdrantClientVersion": "1.15",
        },
        "configFingerprint": sha256_json(config),
        "m4ExperimentFingerprint": m4_experiment_fingerprint(config),
        "rerankerConfigFingerprint": reranker_config_fingerprint(config),
        "rewriteConfigFingerprint": rewrite_config_fingerprint(config),
        "promptFingerprint": "2" * 64,
        "resolvedConfig": config,
        "evaluatedCases": source["caseCount"],
        "partial": False,
    }
    pool = ["merchant:low", "merchant:high", "merchant:medium"]
    results = [
        {
            "id": case["id"],
            "orderedCandidates": [],
            "retrievalTrace": {
                "preRerankCandidateExternalIds": pool,
                "preRerankPoolFingerprint": sha256_json(pool),
                "rerankerInputFingerprint": "a" * 64,
            },
        }
        for case in source["cases"]
    ]
    return {
        "schemaVersion": 4,
        "suite": {
            "suite": source["suite"],
            "split": "dev",
            "caseCount": source["caseCount"],
            "caseSha256": source["caseSha256"],
            "suiteContractSha256": source["suiteContractSha256"],
            "judgmentContractSha256": sha256_json(source["judgmentContract"]),
        },
        "run": run,
        "index": {
            "lifecycleState": "complete",
            "manifestFingerprint": "6" * 64,
            "qdrantServer": {"mode": "server", "version": "1.19"},
        },
        "qualityGate": {"passed": True},
        "results": results,
    }


def _write_dataset(directory):
    directory.mkdir(parents=True)
    values = {
        "shops.json": [
            _shop(1, "merchant:low", []),
            _shop(2, "merchant:high", ["quiet", "vegan"]),
            _shop(3, "merchant:medium", ["quiet"]),
        ],
        "shop_business_hours.json": [],
        "shop_reviews.json": [],
        "blogs.json": [],
        "blog_comments.json": [],
        "import_manifest.json": {
            "dataVersion": "fixture-v1",
            "datasetSha256": "d" * 64,
        },
    }
    for filename, value in values.items():
        (directory / filename).write_text(json.dumps(value), encoding="utf-8")
    return directory


def _shop(shop_id: int, external_id: str, tags: list[str]) -> dict:
    return {
        "id": shop_id,
        "externalId": external_id,
        "name": external_id,
        "typeId": 1,
        "neighborhood": "Midtown",
        "borough": "Manhattan",
        "businessStatus": "OPERATIONAL",
        "avgPriceCents": 2500,
        "tags": tags,
    }


def _comparison_reports(suite: dict, capture: dict) -> tuple[dict, dict]:
    suite_report = {
        "schemaVersion": 5,
        "suite": suite["suite"],
        "split": "dev",
        "caseCount": suite["caseCount"],
        "caseSha256": suite["caseSha256"],
        "suiteContractSha256": suite["suiteContractSha256"],
        "judgmentContract": deepcopy(suite["judgmentContract"]),
        "judgmentContractSha256": sha256_json(suite["judgmentContract"]),
    }

    def report(*, treatment: bool) -> dict:
        provider = "qwen3-rerank" if treatment else "heuristic-multi-signal"
        config = _config(provider)
        results = [
            _result_row(
                case_id=case["id"],
                language=case["language"],
                scenario=case["scenario"],
                treatment=treatment,
            )
            for case in suite["cases"]
        ]
        summary = rounded(_summarize_m4_results(results))
        run = {
            **deepcopy(capture["run"]),
            "configFingerprint": sha256_json(config),
            "m4ExperimentFingerprint": m4_experiment_fingerprint(config),
            "rerankerConfigFingerprint": reranker_config_fingerprint(config),
            "rewriteConfigFingerprint": rewrite_config_fingerprint(config),
            "resolvedConfig": config,
            "rerankerProviderCost": {
                "scoredEstimatedCostUsd": summary["costUsd"]["reranker"],
                "warmupEstimatedCostUsd": 0.0,
                "estimatedCostUsd": summary["costUsd"]["reranker"],
                "hardCostCapUsd": 0.5,
            },
            "policyArtifacts": {
                "qualityGateSha256": hashlib.sha256(DEFAULT_GATE.read_bytes()).hexdigest()
            },
        }
        contract = suite["judgmentContract"]
        manifest = {
            "suiteSchemaVersion": 5,
            "suiteContractSha256": suite["suiteContractSha256"],
            "caseSha256": suite["caseSha256"],
            "judgmentContractSha256": sha256_json(contract),
            "candidateUniverseFixtureSha256": contract[
                "candidateUniverseFixtureSha256"
            ],
            "candidatePoolContractSha256": contract["candidatePoolContractSha256"],
            "configFingerprint": run["configFingerprint"],
            "m4ExperimentFingerprint": run["m4ExperimentFingerprint"],
            "rerankerConfigFingerprint": run["rerankerConfigFingerprint"],
            "rerankerProvider": provider,
            "indexManifestFingerprint": capture["index"]["manifestFingerprint"],
        }
        return {
            "schemaVersion": 5,
            "suite": deepcopy(suite_report),
            "run": run,
            "index": deepcopy(capture["index"]),
            "evaluationManifest": manifest,
            "qualityGate": {"passed": True},
            "summary": summary,
            "results": results,
        }

    return report(treatment=False), report(treatment=True)


def _result_row(*, case_id: str, language: str, scenario: str, treatment: bool) -> dict:
    ndcg = 0.41 if treatment else 0.4
    pool = ["merchant:low", "merchant:high", "merchant:medium"]
    usage = {
        "network_requests": int(treatment),
        "total_tokens": 100 if treatment else 0,
        "retry_count": 0,
        "failure_count": 0,
        "cache_hits": 0,
        "estimated_cost_usd": 0.001 if treatment else 0.0,
    }
    return {
        "id": case_id,
        "language": language,
        "scenario": scenario,
        "semanticRuleCoverage": (
            "outOfDictionary" if scenario == "semantic_alias_composition" else None
        ),
        "metrics": {
            "recallAt5": 0.5,
            "recallAt10": 0.5,
            "precisionAt5": 0.8,
            "ndcgAt5": ndcg,
            "ndcgAt10": 0.5,
            "mrrAt10": 1.0,
            "unjudgedReturnedCount": 0,
            "unjudgedReturnedRate": 0.0,
        },
        "integrity": {
            "hardConstraintSatisfaction": 1.0,
            "hardConstraintViolationCount": 0,
            "hardConstraintUnknownCount": 0,
            "evidenceCoverage": 1.0,
            "duplicateMerchantCount": 0,
            "duplicateMerchantRate": 0.0,
            "duplicateBrandCount": 0,
            "duplicateBrandRate": 0.0,
            "excessiveBrandCount": 0,
            "excessiveBrandRate": 0.0,
            "hardNegativeReturnCount": 0,
            "hardNegativeReturnRate": 0.0,
            "citationCount": 1,
            "citationOwnershipMismatchCount": 0,
            "citationExternalIdMismatchCount": 0,
            "citationSourceMismatchCount": 0,
            "citationSourceMismatchRate": 0.0,
            "securityLeakageCount": 0,
            "versionMismatchCount": 0,
            "versionMismatchRate": 0.0,
            "emptyResult": False,
        },
        "structuredMissRescue": {
            "eligible": False,
            "eligibleRelevantCount": 0,
            "recoveredAt10Count": 0,
            "recallAt10": None,
            "caseRecovered": False,
        },
        "latencyMs": {
            "reranker": 20.0 if treatment else 0.0,
            "total": 500.0 if treatment else 100.0,
        },
        "requests": {
            "embeddingRequests": 1,
            "queryEmbeddingCalls": 1,
            "documentEmbeddingCalls": 0,
            "embeddedTexts": 1,
            "providerUsage": {
                "network_requests": 1,
                "total_tokens": 10,
                "retry_count": 0,
                "failure_count": 0,
                "query_cache_hits": 0,
            },
            "rewriteRequests": 1,
            "rewriteProviderUsage": {
                "network_requests": 1,
                "total_tokens": 100,
                "retry_count": 0,
                "failure_count": 0,
                "query_cache_hits": 0,
                "estimated_cost_usd": 0.001,
            },
            "rerankerRequests": int(treatment),
            "rerankerProviderUsage": usage,
            "rerankerFallback": False,
        },
        "orderedCandidates": [
            {"externalId": "merchant:high", "judged": True, "relevance": 3}
        ],
        "retrievalTrace": {
            "preRerankCandidateExternalIds": pool,
            "preRerankPoolFingerprint": sha256_json(pool),
            "rerankerInputFingerprint": "a" * 64,
            "rerankerCandidates": len(pool),
        },
    }


def _write_reports(tmp_path, control: dict, treatment: dict):
    control_path = tmp_path / "control.json"
    treatment_path = tmp_path / "treatment.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    treatment_path.write_text(json.dumps(treatment), encoding="utf-8")
    return control_path, treatment_path
