from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from evals.rag_v2.build_m3_cases import (
    M3_CANDIDATE_UNIVERSE_FILENAME,
    M3_SELECTION_LEAKAGE_WARNING,
    M3_SUITE_NAME,
    build_m3_dev_suite,
    capture_m3_candidate_universe,
    m3_candidate_universe_sha256,
    m3_experiment_fingerprint,
    m3_suite_contract_sha256,
    rewrite_config_fingerprint,
    validate_frozen_m2_dev_source_suite,
    write_m3_artifacts,
)
from evals.rag_v2.compare_m3 import (
    DEFAULT_GATE,
    _summarize_m3_results,
    compare,
    write_comparison,
)
from evals.rag_v2.contract import sha256_json, suite_contract_sha256
from evals.rag_v2.metrics import rounded


def test_m3_schema_v4_bounded_union_is_deterministic_and_warns_about_selection_leakage(
    tmp_path,
):
    source = _source_suite()
    control_capture, treatment_capture = _capture_reports(source)
    universe = capture_m3_candidate_universe(
        source_suite=source,
        control_report=control_capture,
        treatment_report=treatment_capture,
        candidate_limit=2,
        trusted_source_suite=source,
    )
    data_directory = _write_dataset(tmp_path / "data")

    suite = build_m3_dev_suite(
        data_directory,
        source,
        universe,
        trusted_source_suite=source,
    )

    assert suite["schemaVersion"] == 4
    assert suite["suite"] == M3_SUITE_NAME
    assert suite["evaluationDesign"]["selectionLeakageWarning"] == M3_SELECTION_LEAKAGE_WARNING
    assert suite["judgmentContract"]["unjudgedReturnedPolicy"] == "fail-closed"
    assert suite["judgmentContract"]["m1PolicyHoldoutForbidden"] is True
    assert suite["judgmentContract"]["selectionLeakageWarning"] == M3_SELECTION_LEAKAGE_WARNING
    assert suite["judgmentContract"]["structuredJudgmentPairs"] == 2
    assert suite["judgmentContract"]["m2ControlObservedPairs"] == 2
    assert suite["judgmentContract"]["m3TreatmentObservedPairs"] == 2
    assert suite["judgmentContract"]["boundedJudgmentPairs"] == 6
    assert suite["judgmentContract"]["m3TreatmentOnlyJudgmentPairs"] == 2
    assert suite["judgmentContract"]["binaryRelevantM3TreatmentOnlyPairs"] == 2
    assert suite["caseSha256"] == sha256_json(suite["cases"])
    assert suite["suiteContractSha256"] == m3_suite_contract_sha256(suite)
    assert universe["fixtureSha256"] == m3_candidate_universe_sha256(universe)
    for case in suite["cases"]:
        assert {item["externalId"] for item in case["judgments"]} == {
            "merchant:structured",
            "merchant:control",
            "merchant:treatment",
        }
        treatment = next(
            item for item in case["judgments"] if item["externalId"] == "merchant:treatment"
        )
        assert treatment["relevance"] == 3
        assert treatment["judgmentOrigins"] == ["m3-treatment-top-k"]
        assert case["metadata"]["selectionLeakageWarning"] == M3_SELECTION_LEAKAGE_WARNING


def test_m3_rejects_consumed_m1_test_and_tampered_capture_fingerprints(tmp_path):
    source = _source_suite()
    forbidden = deepcopy(source)
    forbidden["schemaVersion"] = 2
    forbidden["split"] = "test"
    with pytest.raises(ValueError, match="M1 Test"):
        validate_frozen_m2_dev_source_suite(
            forbidden,
            trusted_source_suite=forbidden,
        )

    control, treatment = _capture_reports(source)
    treatment["run"]["promptFingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="treatment requires an enabled, fingerprinted"):
        capture_m3_candidate_universe(
            source_suite=source,
            control_report=control,
            treatment_report=treatment,
            candidate_limit=2,
            trusted_source_suite=source,
        )

    control, treatment = _capture_reports(source)
    universe = capture_m3_candidate_universe(
        source_suite=source,
        control_report=control,
        treatment_report=treatment,
        candidate_limit=2,
        trusted_source_suite=source,
    )
    universe["indexManifestFingerprint"] = "a" * 64
    data_directory = _write_dataset(tmp_path / "data")
    with pytest.raises(ValueError, match="fixture SHA"):
        build_m3_dev_suite(
            data_directory,
            source,
            universe,
            trusted_source_suite=source,
        )


def test_m3_artifact_and_comparison_outputs_refuse_overwrite(tmp_path):
    source = _source_suite()
    control, treatment = _capture_reports(source)
    universe = capture_m3_candidate_universe(
        source_suite=source,
        control_report=control,
        treatment_report=treatment,
        candidate_limit=2,
        trusted_source_suite=source,
    )
    suite = build_m3_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    adversarial = tmp_path / "adversarial.json"
    adversarial.write_text("{}\n", encoding="utf-8")
    output_directory = tmp_path / "frozen"

    paths = write_m3_artifacts(
        output_directory,
        suite=suite,
        candidate_universe=universe,
        adversarial_source=adversarial,
    )
    original = paths["suite"].read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        write_m3_artifacts(
            output_directory,
            suite=suite,
            candidate_universe=universe,
            adversarial_source=adversarial,
        )
    assert paths["suite"].read_bytes() == original
    assert paths["candidateUniverse"].name == M3_CANDIDATE_UNIVERSE_FILENAME

    comparison_path = tmp_path / "comparison.json"
    write_comparison(comparison_path, {"passed": True})
    with pytest.raises(FileExistsError):
        write_comparison(comparison_path, {"passed": False})
    assert json.loads(comparison_path.read_text(encoding="utf-8")) == {"passed": True}


def test_m3_compare_enforces_rewrite_only_pair_and_quality_cost_latency_gates(tmp_path):
    source = _source_suite()
    control_capture, treatment_capture = _capture_reports(source)
    universe = capture_m3_candidate_universe(
        source_suite=source,
        control_report=control_capture,
        treatment_report=treatment_capture,
        candidate_limit=2,
        trusted_source_suite=source,
    )
    suite = build_m3_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    control, treatment = _comparison_reports(suite, control_capture, treatment_capture)
    control_path, treatment_path = _write_reports(tmp_path, control, treatment)

    result = compare(control_path, treatment_path)

    assert result["passed"] is True
    assert result["deltas"] == {
        "overall.recallAt10": 0.025,
        "overall.ndcgAt10": 0.05,
        "bySemanticRuleCoverage.outOfDictionary.recallAt10": 0.05,
        "bySemanticRuleCoverage.outOfDictionary.ndcgAt10": 0.05,
        "overall.precisionAt5": 0.0,
        "overall.mrrAt10": 0.0,
        "overall.hardConstraintSatisfaction": 0.0,
        "byLanguage.zh.ndcgAt10": 0.05,
        "bySemanticRuleCoverage.ruleCovered.ndcgAt10": 0.05,
        "byScenario.negation_exclusion.ndcgAt10": 0.05,
    }
    assert result["ratios"]["latencyMs.total.p95"] == 1.1
    assert result["requestDeltas"]["requestCounts.rewriteProviderTokens"] == 200
    assert result["costs"]["treatment"]["estimatedCostUsd"] == 0.002
    assert result["manifest"]["treatmentPromptFingerprint"] == "b" * 64

    drifted = deepcopy(treatment)
    drifted["run"]["resolvedConfig"]["retrieval"]["candidateLimit"] = 9
    _rebind_config(drifted)
    drifted_path = tmp_path / "drifted.json"
    drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(ValueError, match="config differs from candidate capture"):
        compare(control_path, drifted_path)

    over_budget = deepcopy(treatment)
    for row in over_budget["results"]:
        row["requests"]["rewriteProviderUsage"]["estimated_cost_usd"] = 0.055
    over_budget["summary"] = rounded(_summarize_m3_results(over_budget["results"]))
    over_budget["run"]["rewriteProviderCost"] = {
        "scoredEstimatedCostUsd": 0.11,
        "warmupEstimatedCostUsd": 0.0,
        "estimatedCostUsd": 0.11,
        "hardCostCapUsd": 0.1,
    }
    over_budget_path = tmp_path / "over-budget.json"
    over_budget_path.write_text(json.dumps(over_budget), encoding="utf-8")
    over_budget_result = compare(control_path, over_budget_path)
    assert over_budget_result["passed"] is False
    assert any("estimated cost" in failure for failure in over_budget_result["failures"])


def test_m3_compare_rejects_manifest_tampering_nonfinite_values_and_integer_near_miss(tmp_path):
    source = _source_suite()
    control_capture, treatment_capture = _capture_reports(source)
    universe = capture_m3_candidate_universe(
        source_suite=source,
        control_report=control_capture,
        treatment_report=treatment_capture,
        candidate_limit=2,
        trusted_source_suite=source,
    )
    suite = build_m3_dev_suite(
        _write_dataset(tmp_path / "data"),
        source,
        universe,
        trusted_source_suite=source,
    )
    control, treatment = _comparison_reports(suite, control_capture, treatment_capture)
    control_path, treatment_path = _write_reports(tmp_path, control, treatment)

    manifest_tampered = deepcopy(treatment)
    manifest_tampered["evaluationManifest"]["promptFingerprint"] = "c" * 64
    path = tmp_path / "manifest-tampered.json"
    path.write_text(json.dumps(manifest_tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest promptFingerprint"):
        compare(control_path, path)

    nonfinite = deepcopy(treatment)
    nonfinite["results"][0]["metrics"]["ndcgAt10"] = float("nan")
    path = tmp_path / "nonfinite.json"
    path.write_text(json.dumps(nonfinite), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
        compare(control_path, path)

    nonfinite_cost = deepcopy(treatment)
    nonfinite_cost["results"][0]["requests"]["rewriteProviderUsage"][
        "estimated_cost_usd"
    ] = float("nan")
    path = tmp_path / "nonfinite-cost.json"
    path.write_text(json.dumps(nonfinite_cost), encoding="utf-8")
    with pytest.raises(ValueError, match="finite non-negative float"):
        compare(control_path, path)

    integer_bypass = deepcopy(treatment)
    integer_bypass["summary"]["requestCounts"]["rewriteProviderNetworkRequests"] = 1.999999
    path = tmp_path / "integer-bypass.json"
    path.write_text(json.dumps(integer_bypass), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
        compare(control_path, path)

    rounding = deepcopy(treatment)
    rounding["summary"]["overall"]["ndcgAt10"] += 0.000001
    path = tmp_path / "rounding.json"
    path.write_text(json.dumps(rounding), encoding="utf-8")
    assert compare(control_path, path)["passed"] is True
    rounding["summary"]["overall"]["ndcgAt10"] += 0.000009
    path.write_text(json.dumps(rounding), encoding="utf-8")
    with pytest.raises(ValueError, match="summary does not match"):
        compare(control_path, path)


def _source_suite() -> dict:
    cases = [
        _source_case("dev-en-001", "en", "semantic_alias_composition"),
        _source_case("dev-zh-001", "zh", "negation_exclusion"),
    ]
    suite = {
        "schemaVersion": 3,
        "suite": "rag-v2-m2-fixture-dev-v1",
        "split": "dev",
        "retrievalVersion": "p12-rag-v1",
        "generatorVersion": "m2-test",
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
        "evaluationDesign": {
            "holdout": "m2-dev-only",
            "m1PolicyHoldoutUsed": False,
        },
        "splitIsolation": {"intentGroupOverlap": 0},
        "hardNegativeCoverage": {"declared": 0},
        "adversarialFixtureSha256": "e" * 64,
        "cases": cases,
        "judgmentContract": {
            "policyVersion": "m2-fixture",
            "sourceSplit": "dev",
            "m1PolicyHoldoutUsed": False,
            "candidateUniverseFixtureSha256": "f" * 64,
        },
    }
    suite["suiteContractSha256"] = suite_contract_sha256(suite)
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
                "externalId": "merchant:structured",
                "relevance": 2,
                "matchedPreferences": ["quiet"],
                "hardConstraintViolations": [],
                "hardConstraintUnknowns": [],
                "negativeType": None,
            },
            {
                "shopId": 2,
                "externalId": "merchant:control",
                "relevance": 2,
                "matchedPreferences": ["quiet"],
                "hardConstraintViolations": [],
                "hardConstraintUnknowns": [],
                "negativeType": None,
            },
        ],
        "hardNegatives": [],
        "forbiddenDocumentIds": [],
        "metadata": {"labelPolicyVersion": "derived-merchant-attributes-v1"},
    }


def _resolved_config(*, rewrite_enabled: bool) -> dict:
    provider = "openai" if rewrite_enabled else "disabled"
    prompt_fingerprint = "b" * 64 if rewrite_enabled else None
    return {
        "retrieval": {
            "version": "p12-rag-v1",
            "mode": "global-hybrid",
            "candidateLimit": 2,
            "fusionPoolLimit": 30,
        },
        "embedding": {"identity": "a" * 64},
        "qdrant": {"collection": "m3-test", "reuseIndex": True},
        "features": {
            "globalRetrievalMode": "global-hybrid",
            "globalRetrievalEnabled": True,
            "queryRewriteProvider": provider,
            "queryRewriteEnabled": rewrite_enabled,
            "rerankerProvider": "heuristic-multi-signal",
        },
        "queryRewrite": {
            "enabled": rewrite_enabled,
            "provider": provider,
            "model": "rewrite-test-v1" if rewrite_enabled else "disabled",
            "promptVersion": "m3-prompt-v1" if rewrite_enabled else "disabled",
            "promptFingerprint": prompt_fingerprint,
            "maxQueries": 3,
        },
        "eval": {"split": "dev", "concurrency": 1, "warmupCases": 1},
        "experimentControlFingerprint": "1" * 64 if rewrite_enabled else "2" * 64,
    }


def _capture_reports(source: dict) -> tuple[dict, dict]:
    runtime = {
        "pythonImplementation": "CPython",
        "pythonVersion": "3.13.12",
        "qdrantClientVersion": "1.19.0",
    }
    qdrant_server = {
        "mode": "server",
        "version": "1.19.0",
        "commit": "fixture",
        "metadataAvailable": True,
    }
    source_files = {"agent-service/app/rag/query_rewriter.py": "3" * 64}
    scoped_source = {
        "sha256": sha256_json(source_files),
        "fileSha256": source_files,
        "fileCount": 1,
        "dirty": False,
    }
    suite_report = {
        "schemaVersion": 3,
        "suite": source["suite"],
        "split": "dev",
        "caseCount": source["caseCount"],
        "caseSha256": source["caseSha256"],
        "suiteContractSha256": source["suiteContractSha256"],
        "judgmentContractSha256": sha256_json(source["judgmentContract"]),
    }

    def report(rewrite_enabled: bool) -> dict:
        config = _resolved_config(rewrite_enabled=rewrite_enabled)
        returned = "merchant:treatment" if rewrite_enabled else "merchant:control"
        prompt_fingerprint = config["queryRewrite"]["promptFingerprint"]
        return {
            "schemaVersion": 3,
            "suite": deepcopy(suite_report),
            "run": {
                "git": {"sha": "4" * 40, "dirty": False},
                "evaluatedCases": source["caseCount"],
                "partial": False,
                "embeddingFallbackCount": 0,
                "retrievalFallbackCount": 0,
                "retrievalIdentityConflictCount": 0,
                "retrievalSafetyRejectionCount": 0,
                "rewriteFallbackCount": 0,
                "rewriteSafetyRejectionCount": 0,
                "configFingerprint": sha256_json(config),
                "m3ExperimentFingerprint": m3_experiment_fingerprint(config),
                "rewriteConfigFingerprint": rewrite_config_fingerprint(config),
                "promptFingerprint": prompt_fingerprint,
                "scopedSource": deepcopy(scoped_source),
                "runtimeEnvironment": deepcopy(runtime),
                "resolvedConfig": config,
            },
            "index": {
                "manifestFingerprint": "5" * 64,
                "lifecycleState": "complete",
                "qdrantServer": deepcopy(qdrant_server),
            },
            "qualityGate": {"passed": True},
            "results": [
                {
                    "id": case["id"],
                    "orderedCandidates": [{"externalId": returned}],
                    "retrievalTrace": {
                        "structuredBranchExternalIds": ["merchant:structured"]
                    },
                }
                for case in source["cases"]
            ],
        }

    return report(False), report(True)


def _write_dataset(directory: Path) -> Path:
    directory.mkdir(parents=True)
    shops = [
        _shop(1, "merchant:structured", ["quiet"]),
        _shop(2, "merchant:control", ["quiet"]),
        _shop(3, "merchant:treatment", ["quiet", "vegan"]),
    ]
    values = {
        "shops.json": shops,
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


def _comparison_reports(
    suite: dict,
    control_capture: dict,
    treatment_capture: dict,
) -> tuple[dict, dict]:
    suite_report = {
        "schemaVersion": 4,
        "suite": suite["suite"],
        "split": "dev",
        "caseCount": suite["caseCount"],
        "caseSha256": suite["caseSha256"],
        "suiteContractSha256": suite["suiteContractSha256"],
        "judgmentContract": deepcopy(suite["judgmentContract"]),
        "judgmentContractSha256": sha256_json(suite["judgmentContract"]),
    }

    def report(capture: dict, *, treatment: bool) -> dict:
        results = [
            _result_row(
                case_id=case["id"],
                language=case["language"],
                scenario=case["scenario"],
                ndcg=0.45 if treatment else 0.4,
                total_ms=110.0 if treatment else 100.0,
                rewrite_enabled=treatment,
            )
            for case in suite["cases"]
        ]
        summary = rounded(_summarize_m3_results(results))
        config = deepcopy(capture["run"]["resolvedConfig"])
        run = {
            **deepcopy(capture["run"]),
            "evaluatedCases": suite["caseCount"],
            "rewriteProviderCost": {
                "scoredEstimatedCostUsd": summary["costUsd"]["queryRewrite"],
                "warmupEstimatedCostUsd": 0.0,
                "estimatedCostUsd": summary["costUsd"]["queryRewrite"],
                "hardCostCapUsd": 0.1,
            },
            "policyArtifacts": {
                "qualityGateSha256": hashlib.sha256(DEFAULT_GATE.read_bytes()).hexdigest()
            },
        }
        index = deepcopy(capture["index"])
        contract = suite["judgmentContract"]
        features = config["features"]
        manifest = {
            "suiteSchemaVersion": 4,
            "suiteContractSha256": suite["suiteContractSha256"],
            "caseSha256": suite["caseSha256"],
            "judgmentContractSha256": sha256_json(contract),
            "candidateUniverseFixtureSha256": contract[
                "candidateUniverseFixtureSha256"
            ],
            "configFingerprint": run["configFingerprint"],
            "m3ExperimentFingerprint": run["m3ExperimentFingerprint"],
            "scopedSourceSha256": run["scopedSource"]["sha256"],
            "sourceGitSha": run["git"]["sha"],
            "runtimeEnvironmentFingerprint": sha256_json(run["runtimeEnvironment"]),
            "indexManifestFingerprint": index["manifestFingerprint"],
            "qdrantServerFingerprint": sha256_json(index["qdrantServer"]),
            "embeddingIdentity": config["embedding"]["identity"],
            "retrievalMode": config["retrieval"]["mode"],
            "globalRetrievalEnabled": features["globalRetrievalEnabled"],
            "queryRewriteProvider": features["queryRewriteProvider"],
            "queryRewriteEnabled": features["queryRewriteEnabled"],
            "promptFingerprint": run["promptFingerprint"],
            "rewriteConfigFingerprint": run["rewriteConfigFingerprint"],
        }
        return {
            "schemaVersion": 4,
            "suite": deepcopy(suite_report),
            "run": run,
            "index": index,
            "evaluationManifest": manifest,
            "qualityGate": {"passed": True},
            "summary": summary,
            "results": results,
        }

    return report(control_capture, treatment=False), report(treatment_capture, treatment=True)


def _result_row(
    *,
    case_id: str,
    language: str,
    scenario: str,
    ndcg: float,
    total_ms: float,
    rewrite_enabled: bool,
) -> dict:
    semantic_rule_coverage = (
        "outOfDictionary"
        if scenario == "semantic_alias_composition"
        else "ruleCovered"
    )
    recall = 0.55 if rewrite_enabled and semantic_rule_coverage == "outOfDictionary" else 0.5
    metrics = {
        "recallAt5": 0.5,
        "recallAt10": recall,
        "precisionAt5": 0.8,
        "ndcgAt5": ndcg,
        "ndcgAt10": ndcg,
        "mrrAt10": 1.0,
        "unjudgedReturnedCount": 0,
        "unjudgedReturnedRate": 0.0,
    }
    integrity = {
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
    }
    rewrite_usage = {
        "network_requests": int(rewrite_enabled),
        "total_tokens": 100 if rewrite_enabled else 0,
        "retry_count": 0,
        "failure_count": 0,
        "query_cache_hits": 0,
        "estimated_cost_usd": 0.001 if rewrite_enabled else 0.0,
    }
    return {
        "id": case_id,
        "language": language,
        "scenario": scenario,
        "semanticRuleCoverage": semantic_rule_coverage,
        "metrics": metrics,
        "integrity": integrity,
        "structuredMissRescue": {
            "eligible": False,
            "eligibleRelevantCount": 0,
            "recoveredAt10Count": 0,
            "recallAt10": None,
            "caseRecovered": False,
        },
        "latencyMs": {"total": total_ms},
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
            "rewriteRequests": int(rewrite_enabled),
            "rewriteProviderUsage": rewrite_usage,
            "rerankerRequests": 0,
        },
        "orderedCandidates": [
            {"externalId": "merchant:treatment", "judged": True, "relevance": 3}
        ],
    }


def _write_reports(tmp_path: Path, control: dict, treatment: dict) -> tuple[Path, Path]:
    control_path = tmp_path / "control.json"
    treatment_path = tmp_path / "treatment.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")
    treatment_path.write_text(json.dumps(treatment), encoding="utf-8")
    return control_path, treatment_path


def _rebind_config(report: dict) -> None:
    config = report["run"]["resolvedConfig"]
    report["run"]["configFingerprint"] = sha256_json(config)
    report["run"]["m3ExperimentFingerprint"] = m3_experiment_fingerprint(config)
    report["evaluationManifest"]["configFingerprint"] = report["run"]["configFingerprint"]
    report["evaluationManifest"]["m3ExperimentFingerprint"] = report["run"][
        "m3ExperimentFingerprint"
    ]
