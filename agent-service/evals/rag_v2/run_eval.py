from __future__ import annotations

import argparse
import asyncio
import hashlib
import heapq
import importlib.metadata
import json
import logging
import math
import platform
import subprocess
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient, models

from app.config import Settings
from app.domain.models import UserConstraints
from app.rag.candidate_discovery import (
    GlobalHybridCandidateDiscovery,
    LegacyCandidateDiscovery,
)
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingMetadata,
    EmbeddingService,
    EmbeddingUsage,
    OpenAICompatibleEmbeddingService,
    QwenNativeEmbeddingService,
)
from app.rag.global_retrieval import GlobalRetrievalScope, QdrantGlobalDocumentRetriever
from app.rag.nyc_loader import iter_generated_documents
from app.rag.qdrant_store import REQUIRED_PAYLOAD_INDEXES, QdrantRagService
from app.runtime import _validate_data_directory
from app.tools.services import GeneratedNycShopToolService
from evals.rag_v2.build_m2_cases import (
    M2_CANDIDATE_UNIVERSE_FILENAME,
    M2_JUDGMENT_POLICY_VERSION,
    M2_SUITE_NAME,
    capture_candidate_universe,
    frozen_m1_dev_source_identity,
    validate_frozen_m1_dev_source_suite,
)
from evals.rag_v2.compare_m1 import (
    EXPECTED_PROFILES,
    POLICY_VERSION,
    normalized_dev_control,
)
from evals.rag_v2.compare_m1 import (
    compare as compare_m1_reports,
)
from evals.rag_v2.contract import (
    fixture_contract_sha256,
    m2_candidate_universe_sha256,
    sha256_json,
    suite_contract_sha256,
)
from evals.rag_v2.embedding_profiles import PROFILES, EmbeddingProfile, profile
from evals.rag_v2.metrics import (
    hard_constraint_violations,
    integrity_metrics,
    ranking_metrics,
    rounded,
    structured_miss_metrics,
    summarize_results,
)

EVAL_DIRECTORY = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
INDEX_BUILD_VERSION = "rag-document-transform-v3-m1"
FROZEN_QUALITY_GATE_PATH = EVAL_DIRECTORY / "quality_gate.json"
FROZEN_HASH_BASELINE_PATH = EVAL_DIRECTORY / "baseline.hash64.local.json"
M2_QUALITY_GATE_PATH = EVAL_DIRECTORY / "m2_quality_gate.json"
INDEX_BUILD_SOURCE_PATHS = (
    "agent-service/app/rag/embeddings.py",
    "agent-service/app/rag/lexical.py",
    "agent-service/app/rag/models.py",
    "agent-service/app/rag/nyc_loader.py",
    "agent-service/app/rag/qdrant_store.py",
    "agent-service/evals/rag_v2/embedding_profiles.py",
)
EVAL_SOURCE_PATHS = (
    "agent-service/pyproject.toml",
    "agent-service/uv.lock",
    "agent-service/app/domain/business_hours.py",
    "agent-service/app/domain/models.py",
    "agent-service/app/rag/candidate_discovery.py",
    "agent-service/app/rag/candidate_fusion.py",
    "agent-service/app/rag/display_text.py",
    "agent-service/app/rag/global_retrieval.py",
    *INDEX_BUILD_SOURCE_PATHS,
    "agent-service/app/rag/merchant_aggregation.py",
    "agent-service/app/rag/query_plan.py",
    "agent-service/app/tools/services.py",
    "agent-service/evals/rag_v2/build_cases.py",
    "agent-service/evals/rag_v2/build_m2_cases.py",
    "agent-service/evals/rag_v2/baseline.hash64.local.json",
    "agent-service/evals/rag_v2/compare_m1.py",
    "agent-service/evals/rag_v2/compare_m2.py",
    "agent-service/evals/rag_v2/contract.py",
    "agent-service/evals/rag_v2/metrics.py",
    "agent-service/evals/rag_v2/m2_quality_gate.json",
    "agent-service/evals/rag_v2/quality_gate.json",
    "agent-service/evals/rag_v2/run_eval.py",
)


class TimedEmbeddingService:
    def __init__(self, inner: EmbeddingService):
        self._inner = inner
        self.reset()

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._inner.metadata

    async def embed_query(self, text: str) -> list[float]:
        started = time.perf_counter()
        try:
            return await self._inner.embed_query(text)
        finally:
            self.query_calls += 1
            self.texts += 1
            self.latency_ms += (time.perf_counter() - started) * 1_000

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            return await self._inner.embed_documents(texts)
        finally:
            self.document_calls += 1
            self.texts += len(texts)
            self.latency_ms += (time.perf_counter() - started) * 1_000

    def reset(self) -> None:
        self.query_calls = 0
        self.document_calls = 0
        self.texts = 0
        self.latency_ms = 0.0
        self._usage_baseline = self._inner.usage_snapshot()

    def clear_query_cache(self) -> None:
        self._inner.clear_query_cache()

    def usage_snapshot(self) -> EmbeddingUsage:
        return self._inner.usage_snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "embeddingRequests": self.query_calls + self.document_calls,
            "queryEmbeddingCalls": self.query_calls,
            "documentEmbeddingCalls": self.document_calls,
            "embeddedTexts": self.texts,
            "embeddingLatencyMs": self.latency_ms,
            "providerUsage": self._inner.usage_snapshot().delta(self._usage_baseline).as_dict(),
        }

    async def aclose(self) -> None:
        await self._inner.aclose()


def load_suite(path: Path, data_directory: Path, *, expected_split: str | None = None) -> tuple[dict, dict]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    schema_version = int(suite.get("schemaVersion") or 0)
    if schema_version not in {2, 3}:
        raise ValueError("RAG v2 suite must use schemaVersion=2 or schemaVersion=3.")
    if expected_split and suite.get("split") != expected_split:
        raise ValueError(
            f"Eval suite split={suite.get('split')!r} does not match requested {expected_split!r}."
        )
    cases = suite.get("cases") or []
    if int(suite.get("caseCount") or 0) != len(cases):
        raise ValueError("Eval suite caseCount does not match its case list.")
    canonical = _canonical_json(cases)
    actual_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if suite.get("caseSha256") != actual_sha:
        raise ValueError("Eval suite caseSha256 does not match its canonical case list.")
    actual_contract_sha = suite_contract_sha256(suite)
    if suite.get("suiteContractSha256") != actual_contract_sha:
        raise ValueError("Eval suite suiteContractSha256 does not match its frozen evaluation contract.")
    _validate_adversarial_fixture(path.parent, suite)
    _validate_cases(suite)
    if schema_version == 3:
        _validate_m2_judgment_contract(path.parent, suite)

    validated_data_version, validated_dataset_sha, _ = _validate_data_directory(data_directory)
    if suite.get("dataVersion") != validated_data_version:
        raise ValueError("Eval suite dataVersion does not match the validated corpus files.")
    if suite.get("datasetSha256") != validated_dataset_sha:
        raise ValueError("Eval suite datasetSha256 does not match the validated corpus files.")
    manifest = json.loads((data_directory / "import_manifest.json").read_text(encoding="utf-8"))
    for field in ("dataVersion", "datasetSha256"):
        if suite.get(field) != manifest.get(field):
            raise ValueError(
                f"Eval suite {field}={suite.get(field)!r} does not match corpus "
                f"{manifest.get(field)!r}. Regenerate the suite for this exact corpus."
            )
    return suite, manifest


async def evaluate_case(
    runtime: Any,
    case: dict,
    suite: dict,
    *,
    candidate_limit: int,
    capture_only: bool = False,
) -> dict:
    constraints = UserConstraints.model_validate(case["constraints"])
    runtime.embedding_service.reset()
    total_started = time.perf_counter()

    discovery_metadata: dict[str, Any]
    candidate_discovery = getattr(runtime, "candidate_discovery", None)
    if candidate_discovery is not None:
        started = time.perf_counter()
        ranked = await candidate_discovery.discover(constraints, limit=candidate_limit)
        discovery_ms = (time.perf_counter() - started) * 1_000
        discovery_metadata = dict(ranked.retrieval_metadata or {})
        structured_ms = _timing_value(
            discovery_metadata,
            "structuredSearch",
            "structured",
            "structuredLatencyMs",
            "structuredSearchLatencyMs",
        )
        ranking_ms = _timing_value(
            discovery_metadata,
            "candidateRanking",
            "ranking",
            "rankingLatencyMs",
        )
        structured_candidate_count = _metadata_count(discovery_metadata, "structuredCandidates")
    else:
        started = time.perf_counter()
        candidate_pool = await runtime.shop_service.search(constraints)
        structured_ms = (time.perf_counter() - started) * 1_000

        started = time.perf_counter()
        ranked = await runtime.rag_service.rank_candidates(
            constraints,
            candidate_pool,
            limit=candidate_limit,
        )
        ranking_ms = (time.perf_counter() - started) * 1_000
        discovery_ms = structured_ms + ranking_ms
        discovery_metadata = {
            **dict(candidate_pool.retrieval_metadata or {}),
            **dict(ranked.retrieval_metadata or {}),
            "globalRetrievalEnabled": False,
            "globalRetrievalMode": "candidate-filtered",
        }
        structured_candidate_count = len(candidate_pool.candidates)

    started = time.perf_counter()
    evidence = await runtime.rag_service.retrieve(constraints, ranked)
    evidence_ms = (time.perf_counter() - started) * 1_000
    total_ms = (time.perf_counter() - total_started) * 1_000
    embedding = runtime.embedding_service.snapshot()

    external_ids = [candidate.external_id for candidate in ranked.candidates]
    judgments = {str(item["externalId"]): item for item in case["judgments"]}
    unjudged_external_ids = sorted(
        {str(external_id) for external_id in external_ids if str(external_id) not in judgments}
    )
    judgment_contract = suite.get("judgmentContract") or {}
    if judgment_contract.get("unjudgedReturnedPolicy") == "fail-closed" and unjudged_external_ids:
        raise ValueError(
            f"M2 case {case['id']} returned merchants outside its bounded judgment union: "
            + ", ".join(unjudged_external_ids[:5])
            + ". Recapture the treatment universe and rebuild the Dev suite; these merchants "
            "must never be assigned relevance=0 implicitly."
        )
    if capture_only:
        metrics: dict[str, Any] = {
            "status": "not-scored-candidate-universe-capture",
            "unjudgedReturnedCount": len(unjudged_external_ids),
            "unjudgedReturnedRate": len(unjudged_external_ids) / max(1, len(external_ids)),
        }
    else:
        metrics = ranking_metrics(
            external_ids,
            case["judgments"],
            relevance_threshold=int(suite["binaryRelevanceThreshold"]),
        )
    integrity, violations = integrity_metrics(
        candidates=ranked.candidates,
        evidence=evidence,
        hard_constraints=case["hardConstraints"],
        suite=suite,
        forbidden_document_ids=set(case.get("forbiddenDocumentIds") or []),
        hard_negatives=case.get("hardNegatives") or [],
    )
    case_metadata = case.get("metadata") or {}
    if "structuredCandidateExternalIds" in case_metadata:
        structured_ids = {
            str(item) for item in (case_metadata.get("structuredCandidateExternalIds") or [])
        }
    else:
        structured_ids = set(judgments)
    rescue = structured_miss_metrics(
        external_ids,
        case["judgments"],
        structured_ids,
        relevance_threshold=int(suite["binaryRelevanceThreshold"]),
    )
    ordered = []
    for position, candidate in enumerate(ranked.candidates, start=1):
        judgment = judgments.get(str(candidate.external_id))
        dynamic_violations, dynamic_unknowns = hard_constraint_violations(candidate, case["hardConstraints"])
        ordered.append(
            {
                "rank": position,
                "shopId": candidate.shop_id,
                "externalId": candidate.external_id,
                "name": candidate.name,
                "relevance": int(judgment["relevance"]) if judgment else None,
                "judged": judgment is not None,
                "hardConstraintViolations": dynamic_violations,
                "hardConstraintUnknowns": dynamic_unknowns,
            }
        )

    return {
        "id": case["id"],
        "intentGroup": case["intentGroup"],
        "split": case["split"],
        "language": case["language"],
        "scenario": case["scenario"],
        "query": case["query"],
        "candidatePoolSize": int(
            structured_candidate_count if structured_candidate_count is not None else len(structured_ids)
        ),
        "returnedCount": len(ranked.candidates),
        "relevantJudgmentCount": sum(
            int(item["relevance"]) >= int(suite["binaryRelevanceThreshold"]) for item in case["judgments"]
        ),
        "metrics": metrics,
        "structuredMissRescue": rescue,
        "integrity": integrity,
        "constraintFailures": violations,
        "latencyMs": {
            "structuredSearch": structured_ms,
            "candidateRanking": ranking_ms,
            "candidateDiscovery": discovery_ms,
            "globalRetrieval": _timing_value(
                discovery_metadata,
                "globalRetrieval",
                "global",
                "globalLatencyMs",
                "globalRetrievalLatencyMs",
            ),
            "globalDenseRetrieval": _timing_value(
                discovery_metadata,
                "globalDenseRetrieval",
                "globalDense",
                "denseLatencyMs",
                "globalDenseLatencyMs",
            ),
            "globalSparseRetrieval": _timing_value(
                discovery_metadata,
                "globalSparseRetrieval",
                "globalSparse",
                "sparseLatencyMs",
                "globalSparseLatencyMs",
            ),
            "globalEmbedding": _timing_value(
                discovery_metadata,
                "globalEmbedding",
                "globalEmbeddingLatencyMs",
                "embeddingLatencyMs",
            ),
            "merchantAggregation": _timing_value(
                discovery_metadata,
                "merchantAggregation",
                "aggregation",
                "aggregationLatencyMs",
            ),
            "hydration": _timing_value(
                discovery_metadata,
                "hydration",
                "hydrationLatencyMs",
            ),
            "fusion": _timing_value(
                discovery_metadata,
                "fusion",
                "fusionLatencyMs",
            ),
            "evidenceRetrieval": evidence_ms,
            "embedding": embedding["embeddingLatencyMs"],
            "total": total_ms,
        },
        "requests": {
            "embeddingRequests": embedding["embeddingRequests"],
            "queryEmbeddingCalls": embedding["queryEmbeddingCalls"],
            "documentEmbeddingCalls": embedding["documentEmbeddingCalls"],
            "embeddedTexts": embedding["embeddedTexts"],
            "rewriteRequests": 0,
            "rerankerRequests": 0,
            "providerUsage": embedding["providerUsage"],
        },
        "orderedCandidates": ordered,
        "retrievalTrace": _retrieval_trace(
            discovery_metadata,
            structured_count=len(structured_ids),
            returned_count=len(ranked.candidates),
        ),
        "retrievalMetadata": {
            "candidateDiscovery": discovery_metadata,
            "candidatePool": (
                candidate_pool.retrieval_metadata if candidate_discovery is None else discovery_metadata
            ),
            "ranking": ranked.retrieval_metadata,
            "evidence": evidence.retrieval_metadata,
        },
    }


def _timing_value(metadata: Mapping[str, Any], *names: str) -> float | None:
    containers = [
        metadata,
        metadata.get("latencyMs") or {},
        metadata.get("stageLatencyMs") or {},
        metadata.get("timingMs") or {},
        metadata.get("candidateDiscoveryLatencyMs") or {},
    ]
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for name in names:
            value = container.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value)
                if math.isfinite(value) and value >= 0:
                    return value
    return None


def _metadata_count(metadata: Mapping[str, Any], *names: str) -> int | None:
    containers = [metadata, metadata.get("counts") or {}, metadata.get("trace") or {}]
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for name in names:
            value = container.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


def _retrieval_trace(
    metadata: Mapping[str, Any],
    *,
    structured_count: int,
    returned_count: int,
) -> dict[str, Any]:
    enabled = bool(metadata.get("globalRetrievalEnabled"))

    def count(default: int, *names: str) -> int:
        value = _metadata_count(metadata, *names)
        return default if value is None else value

    return {
        "globalRetrievalEnabled": enabled,
        "globalRetrievalMode": str(
            metadata.get("globalRetrievalMode")
            or metadata.get("candidateDiscoveryMode")
            or metadata.get("mode")
            or ("global-hybrid" if enabled else "candidate-filtered")
        ),
        "structuredCandidates": count(structured_count, "structuredCandidates"),
        "globalDenseDocuments": count(0, "globalDenseDocuments", "denseDocuments", "denseReturned"),
        "globalSparseDocuments": count(0, "globalSparseDocuments", "sparseDocuments", "sparseReturned"),
        "globalDenseReturnedPoints": count(0, "globalDenseReturnedPoints"),
        "globalSparseReturnedPoints": count(0, "globalSparseReturnedPoints"),
        "globalDenseRejectedPoints": count(0, "globalDenseRejectedPoints"),
        "globalSparseRejectedPoints": count(0, "globalSparseRejectedPoints"),
        "globalMerchants": count(0, "globalMerchants"),
        "fusionCandidates": count(returned_count, "fusionCandidates"),
        "structuredOnlyMerchants": count(0, "structuredOnlyMerchants"),
        "qdrantOnlyMerchants": count(0, "qdrantOnlyMerchants"),
        "overlapMerchants": count(0, "overlapMerchants"),
        "duplicateDocumentsSuppressed": count(0, "duplicateDocumentsSuppressed"),
        "duplicateBrandsSuppressed": count(0, "duplicateBrandsSuppressed"),
        "hardConstraintFiltered": count(0, "hardConstraintFiltered"),
        "hydrationRequested": count(0, "hydrationRequested"),
        "hydrationHydrated": count(0, "hydrationHydrated", "hydratedMerchants", "hydratedCandidates"),
        "hydrationFailed": count(0, "hydrationFailed", "hydrationMissing"),
        "identityConflicts": count(0, "identityConflicts"),
        "identityMismatches": count(0, "identityMismatches"),
        "identityConflictShopIds": list(metadata.get("identityConflictShopIds") or []),
        "globalDenseAvailable": metadata.get("globalDenseAvailable"),
        "globalSparseAvailable": metadata.get("globalSparseAvailable"),
        "globalDenseFallbackReason": metadata.get("globalDenseFallbackReason"),
        "globalSparseFallbackReason": metadata.get("globalSparseFallbackReason"),
        "structuredFallback": bool(metadata.get("structuredFallback")),
        "globalFallback": bool(metadata.get("globalFallback")),
        "globalFallbackReason": metadata.get("globalFallbackReason"),
    }


def _m2_retrieval_safety_issues(results: list[dict[str, Any]]) -> dict[str, int]:
    fields = (
        "hydrationFailed",
        "identityMismatches",
        "globalDenseRejectedPoints",
        "globalSparseRejectedPoints",
    )
    return {
        field: sum(
            int((result.get("retrievalTrace") or {}).get(field) or 0)
            for result in results
        )
        for field in fields
    }


async def run(args: argparse.Namespace) -> tuple[dict, bool]:
    _apply_embedding_profile(args)
    _validate_feature_configuration(args)
    repository = Path(__file__).resolve().parents[3]
    data_directory = args.data_directory.resolve()
    cases_path = args.cases or EVAL_DIRECTORY / f"cases.{args.split}.json"
    suite, manifest = load_suite(cases_path.resolve(), data_directory, expected_split=args.split)
    _validate_m1_policy_artifacts(args, suite=suite)
    gate = json.loads(args.quality_gate.read_text(encoding="utf-8"))
    resolved_config = _resolved_config(args, suite)
    runtime_environment = _runtime_environment_snapshot()
    m2_run = int(suite.get("schemaVersion") or 0) == 3 or (
        int(suite.get("schemaVersion") or 0) == 2
        and args.global_retrieval_mode == "global-hybrid"
    )
    initial_m2_source = _scoped_source_snapshot(repository) if m2_run else None
    capture_only = _validate_m2_run_configuration(
        args,
        suite=suite,
        resolved_config=resolved_config,
        repository=repository,
        scoped_source=initial_m2_source,
        runtime_environment=runtime_environment,
    )
    _validate_holdout_authorization(args, resolved_config, suite=suite)
    corpus_preflight = None
    if args.embedding_provider != "hash":
        corpus_preflight = _sample_corpus(
            data_directory,
            int(getattr(args, "preflight_sample_size", 100)),
        )
        _require_expected_corpus_size(corpus_preflight, suite)
    if (
        args.embedding_provider != "hash"
        and _index_action(args) in {"build", "resume"}
        and not (args.preflight_only or args.provider_smoke)
    ):
        await _precheck_index_intent(
            args=args,
            suite=suite,
            resolved_config=resolved_config,
        )
    inner_embedding = _embedding_service(args, resolved_config)
    if args.preflight_only or args.provider_smoke:
        try:
            preflight = await _embedding_preflight(
                inner_embedding,
                data_directory,
                args=args,
                suite=suite,
                corpus=corpus_preflight,
            )
            report = {
                "schemaVersion": 1,
                "generatedAt": datetime.now(UTC).isoformat(),
                "mode": "provider-smoke" if args.provider_smoke else "preflight",
                "embedding": resolved_config["embedding"],
                "preflight": preflight,
            }
            if args.output:
                _write_json(args.output, report)
            print(json.dumps(rounded(report), indent=2, ensure_ascii=False))
            return report, True
        finally:
            await inner_embedding.aclose()
    preflight = None
    if args.embedding_provider != "hash" and _index_action(args) in {"build", "resume"}:
        try:
            preflight = await _embedding_preflight(
                inner_embedding,
                data_directory,
                args=args,
                suite=suite,
                corpus=corpus_preflight,
            )
        except BaseException:
            try:
                await inner_embedding.aclose()
            except BaseException:
                LOGGER.exception("Failed to close embedding provider after preflight failure.")
            raise
    runtime = await _build_runtime(
        args,
        suite,
        data_directory,
        resolved_config,
        inner_embedding=inner_embedding,
        preflight=preflight,
    )
    holdout_receipt: Path | None = None
    try:
        holdout_receipt = _reserve_holdout_receipt(args, resolved_config, suite)
        cases = list(suite["cases"])
        if args.limit_cases is not None:
            cases = cases[: args.limit_cases]
        for warmup_case in cases[: args.warmup_cases]:
            await evaluate_case(
                runtime,
                warmup_case,
                suite,
                candidate_limit=args.candidate_limit,
                capture_only=capture_only,
            )
        runtime.embedding_service.clear_query_cache()

        results = []
        for index, case in enumerate(cases, start=1):
            result = await evaluate_case(
                runtime,
                case,
                suite,
                candidate_limit=args.candidate_limit,
                capture_only=capture_only,
            )
            results.append(result)
            if capture_only:
                print(
                    f"[{index:03d}/{len(cases):03d}] {case['id']} "
                    f"captured={result['returnedCount']} "
                    f"unjudged={result['metrics']['unjudgedReturnedCount']}"
                )
            else:
                print(
                    f"[{index:03d}/{len(cases):03d}] {case['id']} "
                    f"R@10={result['metrics']['recallAt10']:.3f} "
                    f"nDCG@10={result['metrics']['ndcgAt10']:.3f} "
                    f"hard={result['integrity']['hardConstraintSatisfaction']:.3f}"
                )

        if capture_only:
            summary = _candidate_capture_summary(results)
            quality_gate = {
                "passed": True,
                "failures": [],
                "warnings": [
                    "Candidate-universe capture is intentionally not scored; build the "
                    "schema-v3 Dev suite before comparing quality."
                ],
                "relativeStatus": "not-applicable-candidate-capture",
                "thresholds": {},
            }
        else:
            summary = summarize_results(results)
            baseline = _load_baseline(args.baseline_report, split=args.split)
            quality_gate = evaluate_gate(
                summary,
                gate,
                baseline=baseline,
                suite=suite,
                resolved_config=resolved_config,
                partial=len(cases) != int(suite["caseCount"]),
            )
        fallback_count = sum(
            bool(((result.get("retrievalMetadata") or {}).get(stage) or {}).get("embeddingFallback"))
            for result in results
            for stage in ("candidateDiscovery", "ranking", "evidence")
        )
        retrieval_fallback_count = sum(
            bool((result.get("retrievalTrace") or {}).get(name))
            for result in results
            for name in ("structuredFallback", "globalFallback")
        )
        retrieval_fallback_count += sum(
            (result.get("retrievalTrace") or {}).get(name) is False
            for result in results
            if (result.get("retrievalTrace") or {}).get("globalRetrievalEnabled")
            for name in ("globalDenseAvailable", "globalSparseAvailable")
        )
        identity_conflict_count = sum(
            int((result.get("retrievalTrace") or {}).get("identityConflicts") or 0) for result in results
        )
        retrieval_safety_issues = _m2_retrieval_safety_issues(results)
        retrieval_safety_rejection_count = sum(retrieval_safety_issues.values())
        if args.embedding_provider != "hash" and fallback_count:
            quality_gate["failures"].append(
                f"Formal embedding evaluation observed {fallback_count} sparse fallbacks."
            )
            quality_gate["passed"] = False
        if (capture_only or int(suite.get("schemaVersion") or 0) == 3) and retrieval_fallback_count:
            quality_gate["failures"].append(
                f"M2 observed {retrieval_fallback_count} structured/global branch fallbacks."
            )
            quality_gate["passed"] = False
        if (capture_only or int(suite.get("schemaVersion") or 0) == 3) and identity_conflict_count:
            quality_gate["failures"].append(
                f"M2 rejected {identity_conflict_count} merchants with conflicting identities."
            )
            quality_gate["passed"] = False
        if (
            capture_only or int(suite.get("schemaVersion") or 0) == 3
        ) and retrieval_safety_rejection_count:
            quality_gate["failures"].append(
                "M2 observed incomplete hydration, identity mismatches, or rejected global "
                f"points: {retrieval_safety_issues}."
            )
            quality_gate["passed"] = False
        if capture_only and not quality_gate["passed"]:
            raise ValueError(
                "M2 candidate capture observed a fallback, identity problem, incomplete "
                "hydration, or rejected global point; refusing to freeze an incomplete "
                "judgment universe."
            )
        final_scoped_source = _scoped_source_snapshot(repository)
        if initial_m2_source is not None and not _same_scoped_source_snapshot(
            initial_m2_source,
            final_scoped_source,
        ):
            raise ValueError(
                "M2 Eval/retrieval source changed while the run was in progress; refusing "
                "to freeze or compare results from mixed source revisions."
            )
        scoped_source = initial_m2_source or final_scoped_source
        config_fingerprint = _fingerprint(resolved_config)
        experiment_fingerprint = _m2_experiment_fingerprint(resolved_config)
        candidate_universe = None
        if capture_only:
            candidate_universe = capture_candidate_universe(
                source_suite=suite,
                results=results,
                resolved_config=resolved_config,
                config_fingerprint=config_fingerprint,
                experiment_fingerprint=experiment_fingerprint,
                index_manifest_fingerprint=runtime.index_report["manifestFingerprint"],
                scoped_source_sha256=scoped_source["sha256"],
                runtime_environment=runtime_environment,
                qdrant_server=runtime.index_report["qdrantServer"],
                candidate_limit=args.candidate_limit,
            )
            _write_json_exclusive(args.candidate_universe_output, candidate_universe)
        suite_report = {
            key: suite[key]
            for key in (
                "schemaVersion",
                "suite",
                "split",
                "retrievalVersion",
                "dataVersion",
                "datasetSha256",
                "caseCount",
                "caseSha256",
                "suiteContractSha256",
                "binaryRelevanceThreshold",
                "labelPolicyVersion",
                "labelSource",
                "adjudicationStatus",
            )
        }
        if int(suite.get("schemaVersion") or 0) == 3:
            suite_report["judgmentContractSha256"] = sha256_json(suite["judgmentContract"])
            suite_report["judgmentContract"] = suite["judgmentContract"]
        report = {
            "schemaVersion": (3 if capture_only or int(suite.get("schemaVersion") or 0) == 3 else 2),
            "generatedAt": datetime.now(UTC).isoformat(),
            "mode": "m2-candidate-universe-capture" if capture_only else "evaluation",
            "suite": suite_report,
            "run": {
                "git": _git_snapshot(repository),
                "scopedSource": scoped_source,
                "runtimeEnvironment": runtime_environment,
                "configFingerprint": config_fingerprint,
                "m2ExperimentFingerprint": experiment_fingerprint,
                "latencyProfileFingerprint": _latency_profile_fingerprint(resolved_config),
                "resolvedConfig": resolved_config,
                "stageAvailability": _stage_availability(resolved_config, results=results),
                "policyArtifacts": _policy_artifact_snapshot(args),
                "evaluatedCases": len(cases),
                "partial": len(cases) != int(suite["caseCount"]),
                "embeddingFallbackCount": fallback_count,
                "retrievalFallbackCount": retrieval_fallback_count,
                "retrievalIdentityConflictCount": identity_conflict_count,
                "retrievalSafetyRejectionCount": retrieval_safety_rejection_count,
                "retrievalSafetyIssues": retrieval_safety_issues,
            },
            "evaluationManifest": _evaluation_manifest(
                suite=suite,
                resolved_config=resolved_config,
                config_fingerprint=config_fingerprint,
                experiment_fingerprint=experiment_fingerprint,
                scoped_source=scoped_source,
                runtime_environment=runtime_environment,
                index_report=runtime.index_report,
                candidate_universe=candidate_universe,
            ),
            "corpus": {
                "profile": manifest.get("profile"),
                "dataVersion": manifest["dataVersion"],
                "datasetSha256": manifest["datasetSha256"],
            },
            "index": runtime.index_report,
            "providerUsage": _provider_usage_report(
                _merge_usage(
                    getattr(runtime, "prior_provider_usage", EmbeddingUsage()),
                    runtime.embedding_service.usage_snapshot(),
                ),
                args,
            ),
            "qualityGate": quality_gate,
            "summary": summary,
            "results": results,
        }
        report = rounded(report)
        concise = {
            "suite": report["suite"],
            "run": {
                "configFingerprint": report["run"]["configFingerprint"],
                "latencyProfileFingerprint": report["run"]["latencyProfileFingerprint"],
                "evaluatedCases": report["run"]["evaluatedCases"],
                "partial": report["run"]["partial"],
            },
            "index": report["index"],
            "qualityGate": report["qualityGate"],
            "summary": report["summary"],
        }
        print(json.dumps(concise, indent=2, ensure_ascii=False))
        frozen_m2_artifact = capture_only or int(suite.get("schemaVersion") or 0) == 3
        if args.output:
            (_write_json_exclusive if frozen_m2_artifact else _write_json)(args.output, report)
        if args.summary_output:
            (_write_json_exclusive if frozen_m2_artifact else _write_json)(
                args.summary_output,
                concise,
            )
        if holdout_receipt is not None:
            _finalize_holdout_receipt(
                holdout_receipt,
                state="complete",
                report_sha256=_file_sha256(args.output),
            )
        return report, bool(quality_gate["passed"])
    except BaseException as exc:
        if holdout_receipt is not None:
            try:
                _finalize_holdout_receipt(
                    holdout_receipt,
                    state="failed",
                    error_type=type(exc).__name__,
                )
            except Exception:
                LOGGER.exception("Failed to finalize the M1 holdout receipt.")
        try:
            await runtime.close()
        except BaseException:
            LOGGER.exception("Failed to close Eval resources after evaluation failure.")
        raise
    finally:
        await runtime.close()


def evaluate_gate(
    summary: dict,
    gate: dict,
    *,
    baseline: dict | None,
    suite: dict,
    resolved_config: dict,
    partial: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    if partial:
        warnings.append("Quality gate was not enforced because only a subset of cases ran.")
        return {
            "passed": True,
            "failures": [],
            "warnings": warnings,
            "relativeStatus": "skipped-partial",
            "thresholds": gate,
        }
    for path, threshold in (gate.get("absolute") or {}).get("minimums", {}).items():
        value = float(_path(summary, path))
        if value < float(threshold):
            failures.append(f"{path}={value:.6f} is below {threshold}")
    for path, threshold in (gate.get("absolute") or {}).get("maximums", {}).items():
        value = float(_path(summary, path))
        if value > float(threshold):
            failures.append(f"{path}={value:.6f} exceeds {threshold}")

    relative_status = "not-requested"
    if baseline is not None:
        relative_status = "evaluated"
        baseline_suite = baseline.get("suite") or {}
        if (
            baseline_suite.get("split") != suite["split"]
            or baseline_suite.get("caseSha256") != suite["caseSha256"]
            or baseline_suite.get("suiteContractSha256") != suite["suiteContractSha256"]
        ):
            raise ValueError("Baseline report uses a different split, case SHA, or suite contract SHA.")
        baseline_summary = baseline["summary"]
        for path, tolerance in (gate.get("relative") or {}).get("maxDrops", {}).items():
            current = float(_path(summary, path))
            previous = float(_path(baseline_summary, path))
            if current < previous - float(tolerance):
                failures.append(
                    f"{path} dropped {previous - current:.6f}; maximum allowed drop is {tolerance}"
                )
        for path, tolerance in (gate.get("relative") or {}).get("maxIncreases", {}).items():
            current = float(_path(summary, path))
            previous = float(_path(baseline_summary, path))
            if current > previous + float(tolerance):
                failures.append(
                    f"{path} increased {current - previous:.6f}; maximum allowed increase is {tolerance}"
                )
        current_latency = _latency_profile_fingerprint(resolved_config)
        baseline_latency = (baseline.get("run") or {}).get("latencyProfileFingerprint")
        if baseline_latency == current_latency:
            for path, ratio in (gate.get("relative") or {}).get("maxRatios", {}).items():
                current = float(_path(summary, path))
                previous = float(_path(baseline_summary, path))
                if previous > 0 and current > previous * float(ratio):
                    failures.append(f"{path} ratio={current / previous:.6f} exceeds {ratio}")
        else:
            warnings.append("Latency comparison skipped because latency profiles differ.")
    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "relativeStatus": relative_status,
        "thresholds": gate,
    }


async def _build_runtime(
    args: argparse.Namespace,
    suite: dict,
    data_directory: Path,
    resolved_config: dict,
    *,
    inner_embedding: EmbeddingService,
    preflight: dict | None,
) -> Any:
    prior_provider_usage = _prior_index_provider_usage(args)
    embedding = TimedEmbeddingService(inner_embedding)
    client = _qdrant_client(args.qdrant_location)
    rag = QdrantRagService(
        client=client,
        embeddings=embedding,
        collection_name=args.collection,
        index_batch_size=args.index_batch_size,
        dataset_sha256=suite["datasetSha256"],
        retrieval_version=suite["retrievalVersion"],
        allow_sparse_fallback=False,
    )
    index_started = time.perf_counter()
    manifest_path = args.index_manifest or _default_index_manifest(
        args.qdrant_location,
        args.collection,
    )
    try:
        action = _index_action(args)
        if action == "reuse":
            index_stats = await _validate_reused_index(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
            )
        else:
            await _prepare_index_build(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
                action=action,
                preflight=preflight,
            )
            usage_before_index = embedding.usage_snapshot()
            stats = await rag.sync(
                iter_generated_documents(data_directory),
                data_version=suite["dataVersion"],
            )
            expected_points = int(suite.get("indexedDocuments") or 0)
            if stats.total_documents != expected_points:
                raise ValueError(
                    f"Index sync produced {stats.total_documents} documents; the frozen suite "
                    f"requires exactly {expected_points}."
                )
            index_stats = stats.as_metadata()
            index_usage = embedding.usage_snapshot().delta(usage_before_index)
            readiness = await _wait_for_collection_ready(
                client,
                args.collection,
                expected_points=expected_points,
                timeout_seconds=args.qdrant_ready_timeout_seconds,
                require_server_ready=_location_kind(args.qdrant_location) == "remote",
                visibility_filter=_index_identity_filter(suite, resolved_config),
            )
            await _write_complete_index_manifest(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
                point_count=expected_points,
                index_usage=index_usage,
                attempt_usage=embedding.usage_snapshot(),
                readiness=readiness,
                preflight=preflight,
            )
        index_elapsed_ms = (time.perf_counter() - index_started) * 1_000
        info = await client.get_collection(args.collection)
        count = int((await client.count(args.collection, exact=True)).count)
        expected_points = int(suite.get("indexedDocuments") or 0)
        if count != expected_points:
            raise ValueError(f"Evaluation collection contains {count} points; expected {expected_points}.")
        current_qdrant_server = await _qdrant_server_metadata(args.qdrant_location)
        index_report = {
            "stats": index_stats,
            "pointCount": count,
            "vectorDimensions": _vector_dimensions(info),
            "indexBuildVersion": INDEX_BUILD_VERSION,
            "indexSchema": _index_schema_snapshot(info),
            "indexDurationMs": index_elapsed_ms,
            "collectionBytes": _directory_size(args.qdrant_location),
            "manifestPathKind": "explicit" if args.index_manifest else "sidecar",
            "manifestFingerprint": _manifest_fingerprint(manifest_path),
            "configVerified": _index_manifest_matches(
                manifest_path,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                required_state="complete",
            ),
            "lifecycleState": "complete",
            "qdrantServer": current_qdrant_server,
            "preflight": preflight,
        }
        if int(suite.get("schemaVersion") or 0) == 3:
            expected_manifest = suite["judgmentContract"].get(
                "captureIndexManifestFingerprint"
            )
            if index_report["manifestFingerprint"] != expected_manifest:
                raise ValueError(
                    "M2 index manifest differs from the one used to capture its bounded "
                    "candidate universe."
                )
            if suite["judgmentContract"].get("captureQdrantServer") != current_qdrant_server:
                raise ValueError(
                    "M2 Qdrant Server metadata differs from candidate capture; recapture "
                    "the bounded Dev suite."
                )
    except BaseException:
        if _index_action(args) in {"build", "resume"}:
            try:
                _record_failed_build_attempt(manifest_path, embedding.usage_snapshot(), args)
            except BaseException:
                LOGGER.exception("Failed to persist interrupted embedding build usage.")
        await _close_eval_resources(embedding, client, suppress_errors=True)
        raise

    closed = False

    async def close() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        await _close_eval_resources(embedding, client)

    try:
        shop_service = GeneratedNycShopToolService(
            data_directory,
            max_candidates=args.discovery_pool_size,
        )
        if args.global_retrieval_enabled:
            scope = GlobalRetrievalScope(
                collection_name=args.collection,
                data_version=suite["dataVersion"],
                dataset_sha256=suite["datasetSha256"],
                retrieval_version=suite["retrievalVersion"],
                embedding_identity=embedding.metadata.identity,
            )
            global_retriever = QdrantGlobalDocumentRetriever(
                client,
                embedding,
                scope,
                document_limit=args.global_document_limit,
            )
            candidate_discovery = GlobalHybridCandidateDiscovery(
                shop_service,
                rag,
                global_retriever,
                document_limit=args.global_document_limit,
                hydration_limit=args.global_merchant_limit,
                hydration_concurrency=args.global_hydration_concurrency,
                branch_timeout_seconds=args.global_branch_timeout_seconds,
                documents_per_merchant=args.global_documents_per_merchant,
                rrf_k=args.fusion_rrf_k,
                brand_cap=args.brand_cap,
            )
        else:
            candidate_discovery = LegacyCandidateDiscovery(shop_service, rag)
    except BaseException:
        await _close_eval_resources(embedding, client, suppress_errors=True)
        raise

    return SimpleNamespace(
        shop_service=shop_service,
        rag_service=rag,
        candidate_discovery=candidate_discovery,
        embedding_service=embedding,
        index_report=index_report,
        prior_provider_usage=prior_provider_usage,
        close=close,
    )


async def _close_eval_resources(
    embedding: TimedEmbeddingService,
    client: AsyncQdrantClient,
    *,
    suppress_errors: bool = False,
) -> None:
    errors: list[BaseException] = []
    for close in (embedding.aclose, client.close):
        try:
            await close()
        except BaseException as exc:
            errors.append(exc)
    if suppress_errors or not errors:
        return
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup("Multiple Eval resources failed to close.", errors)


async def _validate_reused_index(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
) -> dict[str, int]:
    current_server = await _require_qdrant_server_contract(args.qdrant_location)
    if not await client.collection_exists(args.collection):
        raise ValueError("--reuse-index requires an existing collection.")
    info = await client.get_collection(args.collection)
    dimensions = _vector_dimensions(info)
    expected_dimensions = int(resolved_config["embedding"]["dimensions"])
    if dimensions != expected_dimensions:
        raise ValueError(
            f"Existing collection uses {dimensions} dimensions; config requests {expected_dimensions}."
        )
    _require_expected_index_schema(
        info,
        expected_dimensions,
        require_payload_indexes=_location_kind(args.qdrant_location) == "remote",
    )
    total = int((await client.count(args.collection, exact=True)).count)
    expected = int(suite.get("indexedDocuments") or 0)
    if expected and total != expected:
        raise ValueError(f"Existing collection contains {total} points; suite expects {expected}.")
    matching_filter = _index_identity_filter(suite, resolved_config)
    matching = int(
        (
            await client.count(
                args.collection,
                count_filter=matching_filter,
                exact=True,
            )
        ).count
    )
    if matching != total:
        raise ValueError(
            "Existing collection mixes another corpus or retrieval version "
            f"({matching}/{total} points match the frozen suite)."
        )
    if not _index_manifest_matches(
        manifest_path,
        args=args,
        suite=suite,
        resolved_config=resolved_config,
        required_state="complete",
    ):
        raise ValueError(
            "Reusing an index requires a matching --index-manifest; point count and vector "
            "dimensions alone cannot identify the embedding implementation."
        )
    _require_reused_server_version(
        args.qdrant_location,
        manifest_path,
        current_server=current_server,
    )
    await _wait_for_collection_ready(
        client,
        args.collection,
        expected_points=expected or total,
        timeout_seconds=float(getattr(args, "qdrant_ready_timeout_seconds", 1_800.0)),
        require_server_ready=_location_kind(args.qdrant_location) == "remote",
        visibility_filter=matching_filter,
    )
    return {"total": total, "upserted": 0, "unchanged": total, "deleted": 0}


async def _require_compatible_collection(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
) -> None:
    """Backward-compatible build guard used by M0 tests and older callers."""

    await _prepare_index_build(
        client,
        args=args,
        suite=suite,
        resolved_config=resolved_config,
        manifest_path=manifest_path,
        action="build",
        preflight=None,
    )


async def _prepare_index_build(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
    action: str,
    preflight: dict | None,
) -> None:
    if action not in {"build", "resume"}:
        raise ValueError(f"Unsupported index build action: {action}")
    exists = await client.collection_exists(args.collection)
    if action == "resume":
        if not manifest_path.is_file() or not _index_manifest_matches(
            manifest_path,
            args=args,
            suite=suite,
            resolved_config=resolved_config,
            required_state="building",
        ):
            raise ValueError("--index-action resume requires an exact state=building index manifest.")
        if exists:
            await _validate_partial_collection(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
            )
        return

    if exists:
        raise ValueError(
            "An index build never adopts an existing collection, even when it is empty. "
            "Use a new collection or --index-action resume with its exact building manifest."
        )
    if manifest_path.exists():
        raise ValueError(
            "Index manifest already exists. Use a new collection or explicitly resume its build."
        )
    _write_json_atomic(
        manifest_path,
        _building_manifest(
            args=args,
            suite=suite,
            resolved_config=resolved_config,
            preflight=preflight,
        ),
    )


async def _precheck_index_intent(
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
) -> None:
    manifest_path = args.index_manifest or _default_index_manifest(
        args.qdrant_location,
        args.collection,
    )
    action = _index_action(args)
    await _require_qdrant_server_contract(args.qdrant_location)
    if action == "build" and manifest_path.exists():
        raise ValueError("Index manifest already exists; refusing paid preflight before an invalid build.")
    if action == "resume" and not _index_manifest_matches(
        manifest_path,
        args=args,
        suite=suite,
        resolved_config=resolved_config,
        required_state="building",
    ):
        raise ValueError("Resume requires an exact state=building manifest before any paid preflight.")
    client = _qdrant_client(args.qdrant_location)
    try:
        exists = await client.collection_exists(args.collection)
        if action == "build" and exists:
            raise ValueError("Collection already exists; refusing paid preflight for a new build.")
        if action == "resume" and exists:
            await _validate_partial_collection(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
            )
    finally:
        await client.close()


async def _validate_partial_collection(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
) -> None:
    if not await client.collection_exists(args.collection):
        return
    total = int((await client.count(args.collection, exact=True)).count)
    info = await client.get_collection(args.collection)
    actual_dimensions = _vector_dimensions(info)
    expected_dimensions = int(resolved_config["embedding"]["dimensions"])
    if actual_dimensions != expected_dimensions:
        raise ValueError(
            f"Evaluation collection uses {actual_dimensions} dimensions; "
            f"config requests {expected_dimensions}. Use a new collection."
        )
    _require_expected_index_schema(
        info,
        expected_dimensions,
        require_payload_indexes=_location_kind(args.qdrant_location) == "remote",
    )
    if not total:
        return
    matching_filter = _index_identity_filter(suite, resolved_config)
    matching = int(
        (
            await client.count(
                args.collection,
                count_filter=matching_filter,
                exact=True,
            )
        ).count
    )
    if matching != total:
        raise ValueError(
            "Partial collection contains points from another corpus, retrieval version, or "
            "embedding identity."
        )


def _index_identity_filter(suite: dict, resolved_config: dict) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="data_version",
                match=models.MatchValue(value=suite["dataVersion"]),
            ),
            models.FieldCondition(
                key="dataset_sha256",
                match=models.MatchValue(value=suite["datasetSha256"]),
            ),
            models.FieldCondition(
                key="retrieval_version",
                match=models.MatchValue(value=suite["retrievalVersion"]),
            ),
            models.FieldCondition(
                key="embedding_identity",
                match=models.MatchValue(value=resolved_config["embedding"]["identity"]),
            ),
        ]
    )


def _building_manifest(
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    preflight: dict | None,
) -> dict:
    return {
        "schemaVersion": 2,
        "state": "building",
        "buildId": str(uuid.uuid4()),
        "createdAt": datetime.now(UTC).isoformat(),
        "collection": args.collection,
        "dataVersion": suite["dataVersion"],
        "datasetSha256": suite["datasetSha256"],
        "expectedPointCount": int(suite.get("indexedDocuments") or 0),
        "retrievalVersion": suite["retrievalVersion"],
        "embedding": resolved_config["embedding"],
        "qdrantEndpointFingerprint": resolved_config["qdrant"].get("endpointFingerprint"),
        "indexBuildVersion": INDEX_BUILD_VERSION,
        "indexBuildSourceFingerprint": resolved_config["retrieval"]["indexBuildSourceFingerprint"],
        "indexSchema": _expected_index_schema(
            int(resolved_config["embedding"]["dimensions"]),
            include_payload_indexes=resolved_config["qdrant"]["locationKind"] == "remote",
        ),
        "vectorDimensions": int(resolved_config["embedding"]["dimensions"]),
        "preflight": preflight,
        "cumulativeProviderUsage": EmbeddingUsage().as_dict(),
        "attempts": [],
    }


async def _write_complete_index_manifest(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
    point_count: int,
    index_usage: EmbeddingUsage,
    readiness: dict,
    preflight: dict | None,
    attempt_usage: EmbeddingUsage | None = None,
) -> None:
    info = await client.get_collection(args.collection)
    expected_points = int(suite.get("indexedDocuments") or 0)
    exact_points = int((await client.count(args.collection, exact=True)).count)
    if point_count != expected_points or exact_points != expected_points:
        raise ValueError(
            "A complete index manifest requires both sync and exact Qdrant counts to equal "
            f"the frozen {expected_points} documents; got sync={point_count}, "
            f"qdrant={exact_points}."
        )
    _require_expected_index_schema(
        info,
        int(resolved_config["embedding"]["dimensions"]),
        require_payload_indexes=_location_kind(args.qdrant_location) == "remote",
    )
    if manifest_path.is_file():
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        value = _building_manifest(
            args=args,
            suite=suite,
            resolved_config=resolved_config,
            preflight=preflight,
        )
    attempt_usage = attempt_usage or index_usage
    prior_usage = _usage_from_dict(value.get("cumulativeProviderUsage") or {})
    cumulative_usage = _merge_usage(prior_usage, attempt_usage)
    attempts = list(value.get("attempts") or [])
    attempts.append(
        {
            "completedAt": datetime.now(UTC).isoformat(),
            "outcome": "complete",
            "usage": attempt_usage.as_dict(),
        }
    )
    value.update(
        {
            "state": "complete",
            "completedAt": datetime.now(UTC).isoformat(),
            "indexSchema": _index_schema_snapshot(info),
            "pointCount": exact_points,
            "vectorDimensions": _vector_dimensions(info),
            "indexProviderUsage": _provider_usage_report(index_usage, args),
            "cumulativeProviderUsage": cumulative_usage.as_dict(),
            "cumulativeProviderCost": _provider_usage_report(cumulative_usage, args),
            "attempts": attempts,
            "readiness": readiness,
            "qdrantServer": await _qdrant_server_metadata(args.qdrant_location),
        }
    )
    _write_json_atomic(manifest_path, value)


def _record_failed_build_attempt(
    manifest_path: Path,
    attempt_usage: EmbeddingUsage,
    args: argparse.Namespace,
) -> None:
    if not manifest_path.is_file():
        return
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if value.get("state") != "building":
        return
    prior_usage = _usage_from_dict(value.get("cumulativeProviderUsage") or {})
    cumulative_usage = _merge_usage(prior_usage, attempt_usage)
    attempts = list(value.get("attempts") or [])
    attempts.append(
        {
            "completedAt": datetime.now(UTC).isoformat(),
            "outcome": "failed",
            "usage": attempt_usage.as_dict(),
        }
    )
    value.update(
        {
            "cumulativeProviderUsage": cumulative_usage.as_dict(),
            "cumulativeProviderCost": _provider_usage_report(cumulative_usage, args),
            "attempts": attempts,
        }
    )
    _write_json_atomic(manifest_path, value)


def _index_manifest_matches(
    path: Path,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    required_state: str = "complete",
) -> bool:
    if not path.is_file():
        return False
    value = json.loads(path.read_text(encoding="utf-8"))
    expected_points = int(suite.get("indexedDocuments") or 0)
    complete_count_matches = (
        required_state != "complete" or int(value.get("pointCount") or 0) == expected_points
    )
    return all(
        (
            value.get("collection") == args.collection,
            value.get("state") == required_state,
            value.get("dataVersion") == suite["dataVersion"],
            value.get("datasetSha256") == suite["datasetSha256"],
            value.get("retrievalVersion") == suite["retrievalVersion"],
            value.get("embedding") == resolved_config["embedding"],
            value.get("qdrantEndpointFingerprint") == resolved_config["qdrant"].get("endpointFingerprint"),
            value.get("indexBuildVersion") == INDEX_BUILD_VERSION,
            value.get("indexBuildSourceFingerprint")
            == resolved_config["retrieval"].get("indexBuildSourceFingerprint"),
            int(value.get("expectedPointCount") or 0) == expected_points,
            complete_count_matches,
            value.get("indexSchema")
            == _expected_index_schema(
                int(resolved_config["embedding"]["dimensions"]),
                include_payload_indexes=(resolved_config["qdrant"]["locationKind"] == "remote"),
            ),
            int(value.get("vectorDimensions") or 0) == int(resolved_config["embedding"]["dimensions"]),
        )
    )


def _apply_embedding_profile(args: argparse.Namespace) -> None:
    profile_id = getattr(args, "embedding_profile", None)
    if not profile_id:
        return
    selected = profile(profile_id)
    conflicts = []
    if args.embedding_provider not in {"hash", selected.provider}:
        conflicts.append("--embedding-provider")
    if args.embedding_model not in {None, selected.model}:
        conflicts.append("--embedding-model")
    if args.embedding_version not in {None, selected.version}:
        conflicts.append("--embedding-version")
    if args.embedding_dimensions not in {64, selected.dimensions}:
        conflicts.append("--embedding-dimensions")
    if args.collection not in {"hmdp_content_v2", selected.collection}:
        conflicts.append("--collection")
    configured_cap = getattr(args, "max_provider_cost_usd", None)
    if configured_cap is not None and configured_cap > selected.max_cost_usd:
        conflicts.append("--max-provider-cost-usd")
    if conflicts:
        raise ValueError(f"Embedding profile {profile_id!r} conflicts with: {', '.join(conflicts)}.")
    args.embedding_provider = selected.provider
    args.embedding_model = selected.model
    args.embedding_version = selected.version
    args.embedding_dimensions = selected.dimensions
    args.collection = selected.collection
    if configured_cap is None:
        args.max_provider_cost_usd = selected.max_cost_usd


def _selected_profile(args: argparse.Namespace) -> EmbeddingProfile | None:
    profile_id = getattr(args, "embedding_profile", None)
    return profile(profile_id) if profile_id else None


def _embedding_service(args: argparse.Namespace, config: dict) -> EmbeddingService:
    settings = _eval_settings()
    configured_token_budget = config["embedding"].get("maxTotalTokens")
    prior_usage = _prior_index_provider_usage(args)
    remaining_token_budget = (
        max(int(configured_token_budget) - prior_usage.total_tokens, 0)
        if configured_token_budget is not None
        else None
    )
    if configured_token_budget is not None and remaining_token_budget == 0:
        raise ValueError("Embedding token budget is already exhausted by prior build attempts.")
    common = {
        "version": str(config["embedding"]["version"]),
        "batch_size": getattr(args, "embedding_batch_size", 64),
        "max_concurrency": getattr(args, "embedding_max_concurrency", 2),
        "timeout_seconds": getattr(args, "embedding_timeout_seconds", 30.0),
        "max_retries": getattr(args, "embedding_max_retries", 4),
        "max_batch_characters": getattr(args, "embedding_max_batch_characters", 250_000),
        "query_cache_size": getattr(args, "embedding_query_cache_size", 512),
        "query_cache_ttl_seconds": getattr(
            args,
            "embedding_query_cache_ttl_seconds",
            900.0,
        ),
        "max_total_tokens": remaining_token_budget,
    }
    if args.embedding_provider == "openai":
        return OpenAICompatibleEmbeddingService(
            base_url=args.embedding_base_url or settings.embedding_base_url,
            api_key=(
                settings.openai_embedding_api_key.get_secret_value()
                or settings.embedding_api_key.get_secret_value()
            ),
            model=str(config["embedding"]["model"]),
            dimensions=int(config["embedding"]["dimensions"]),
            **common,
        )
    if args.embedding_provider == "qwen":
        return QwenNativeEmbeddingService(
            base_url=(
                args.embedding_base_url or settings.qwen_embedding_base_url or settings.embedding_base_url
            ),
            api_key=(
                settings.qwen_embedding_api_key.get_secret_value()
                or settings.embedding_api_key.get_secret_value()
            ),
            model=str(config["embedding"]["model"]),
            dimensions=int(config["embedding"]["dimensions"]),
            query_instruct=getattr(args, "embedding_query_instruct", ""),
            **common,
        )
    return DeterministicHashEmbeddingService(
        dimensions=int(config["embedding"]["dimensions"]),
        version=str(config["embedding"]["version"]),
    )


def _prior_index_provider_usage(args: argparse.Namespace) -> EmbeddingUsage:
    if getattr(args, "embedding_provider", "hash") == "hash":
        return EmbeddingUsage()
    manifest_path = getattr(args, "index_manifest", None) or _default_index_manifest(
        args.qdrant_location,
        args.collection,
    )
    if not manifest_path.is_file():
        return EmbeddingUsage()
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if value.get("state") not in {"building", "complete"}:
        return EmbeddingUsage()
    return _usage_from_dict(value.get("cumulativeProviderUsage") or {})


def _resolved_config(args: argparse.Namespace, suite: dict) -> dict[str, Any]:
    _apply_embedding_profile(args)
    repository = Path(__file__).resolve().parents[3]
    selected = _selected_profile(args)
    if args.embedding_provider == "hash":
        model = args.embedding_model or "deterministic-token-sha256"
        version = args.embedding_version or "hash-v1"
        endpoint_fingerprint = None
    else:
        settings = _eval_settings()
        model = args.embedding_model or settings.embedding_model
        version = args.embedding_version or "provider-revision-unavailable"
        if args.embedding_provider == "qwen":
            base_url = (
                args.embedding_base_url or settings.qwen_embedding_base_url or settings.embedding_base_url
            ).rstrip("/")
        else:
            base_url = (args.embedding_base_url or settings.embedding_base_url).rstrip("/")
        endpoint_fingerprint = hashlib.sha256(base_url.encode()).hexdigest()
    embedding_config: dict[str, Any] = {
        "provider": args.embedding_provider,
        "model": model,
        "dimensions": args.embedding_dimensions,
        "version": version,
        "metadataSource": "configured",
    }
    if endpoint_fingerprint is not None:
        embedding_config["endpointFingerprint"] = endpoint_fingerprint
    if selected is not None and selected.provider != "hash":
        metadata = EmbeddingMetadata(
            provider=selected.provider,
            model=selected.model,
            dimensions=selected.dimensions,
            version=selected.version,
            query_mode=selected.query_mode,
            document_mode=selected.document_mode,
        )
        embedding_config.update(
            {
                "profileId": selected.profile_id,
                "apiFlavor": selected.api_flavor,
                "queryMode": selected.query_mode,
                "documentMode": selected.document_mode,
                "identity": metadata.identity,
                "priceUsdPerMillionTokens": selected.price_usd_per_million_tokens,
                "maxProviderCostUsd": args.max_provider_cost_usd,
                "maxTotalTokens": int(
                    args.max_provider_cost_usd / selected.price_usd_per_million_tokens * 1_000_000
                ),
                "pricingSnapshotDate": "2026-08-31",
                "runtime": {
                    "configuredBatchSize": args.embedding_batch_size,
                    "providerBatchLimit": selected.provider_batch_limit,
                    "effectiveBatchSize": min(
                        args.embedding_batch_size,
                        selected.provider_batch_limit,
                    ),
                    "maxConcurrency": args.embedding_max_concurrency,
                    "timeoutSeconds": args.embedding_timeout_seconds,
                    "maxRetries": args.embedding_max_retries,
                    "maxBatchCharacters": args.embedding_max_batch_characters,
                    "queryCacheSize": args.embedding_query_cache_size,
                    "queryCacheTtlSeconds": args.embedding_query_cache_ttl_seconds,
                },
            }
        )
    elif args.embedding_provider == "hash":
        embedding_config["identity"] = EmbeddingMetadata(
            provider="hash",
            model=str(model),
            dimensions=args.embedding_dimensions,
            version=str(version),
            query_mode="symmetric",
            document_mode="symmetric",
        ).identity
    qdrant_config: dict[str, Any] = {
        "collection": args.collection,
        "locationKind": _location_kind(args.qdrant_location),
        "reuseIndex": _index_action(args) == "reuse",
    }
    if qdrant_config["locationKind"] == "remote":
        qdrant_config["endpointFingerprint"] = _endpoint_fingerprint(args.qdrant_location)
    resolved = {
        "retrieval": {
            "version": suite["retrievalVersion"],
            "candidateLimit": args.candidate_limit,
            "discoveryPoolSize": args.discovery_pool_size,
            "mode": args.global_retrieval_mode,
            "globalDocumentLimit": args.global_document_limit,
            "globalMerchantLimit": args.global_merchant_limit,
            "globalDocumentsPerMerchant": args.global_documents_per_merchant,
            "globalHydrationConcurrency": args.global_hydration_concurrency,
            "globalBranchTimeoutSeconds": args.global_branch_timeout_seconds,
            "fusionRrfK": args.fusion_rrf_k,
            "brandCap": args.brand_cap,
            "queryExpansion": "rules-v1",
            "indexBuildVersion": INDEX_BUILD_VERSION,
            "indexBuildSourceFingerprint": _file_set_fingerprint(
                repository,
                INDEX_BUILD_SOURCE_PATHS,
            )["sha256"],
        },
        "embedding": embedding_config,
        "qdrant": qdrant_config,
        "features": {
            "queryRewriteProvider": args.query_rewrite_provider,
            "globalRetrievalMode": args.global_retrieval_mode,
            "globalRetrievalEnabled": bool(args.global_retrieval_enabled),
            "rerankerProvider": args.reranker_provider,
        },
        "eval": {
            "split": args.split,
            "warmupCases": args.warmup_cases,
            "concurrency": 1,
            "latencyMode": "outer-wall-clock-sequential",
        },
    }
    if selected is not None and selected.provider != "hash":
        control = {
            "retrieval": resolved["retrieval"],
            "qdrant": {
                key: value
                for key, value in resolved["qdrant"].items()
                if key not in {"collection", "endpointFingerprint"}
            },
            "features": resolved["features"],
            "eval": resolved["eval"],
            "embeddingDimensions": args.embedding_dimensions,
            "embeddingRuntime": {
                key: value
                for key, value in embedding_config["runtime"].items()
                if key not in {"providerBatchLimit", "effectiveBatchSize"}
            },
        }
        resolved["experimentControlFingerprint"] = _fingerprint(control)
    return resolved


def _eval_settings() -> Settings:
    """Read credentials/endpoints without letting runtime provider env override an Eval profile."""

    return Settings(environment="development", embedding_provider="hash")


def _stage_availability(
    resolved_config: dict,
    *,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    real_embedding = resolved_config["embedding"]["provider"] != "hash"
    global_enabled = bool((resolved_config.get("features") or {}).get("globalRetrievalEnabled"))
    availability = {
        "structuredSearch": {"available": True, "source": "eval-outer-timer"},
        "candidateRanking": {"available": True, "source": "eval-outer-timer"},
        "candidateDiscovery": {"available": True, "source": "eval-outer-timer"},
        "evidenceRetrieval": {"available": True, "source": "eval-outer-timer"},
        "embedding": {"available": True, "source": "eval-wrapper"},
        "queryPlanning": {
            "available": False,
            "reason": "current service does not expose an isolated planning timer",
        },
        "globalRetrieval": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "globalDenseRetrieval": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "globalSparseRetrieval": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "globalEmbedding": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "merchantAggregation": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "hydration": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "fusion": {
            "available": global_enabled,
            "source": "candidate-discovery-metadata" if global_enabled else "disabled-control",
        },
        "rewrite": {"available": False, "reason": "disabled in M0 baseline"},
        "reranker": {"available": False, "reason": "no learned reranker in M0 baseline"},
        "providerUsage": {
            "available": real_embedding,
            "source": "provider-response-usage" if real_embedding else "not-applicable-hash",
        },
    }
    if results:
        for stage in (
            "structuredSearch",
            "candidateRanking",
            "candidateDiscovery",
            "globalRetrieval",
            "globalDenseRetrieval",
            "globalSparseRetrieval",
            "globalEmbedding",
            "merchantAggregation",
            "hydration",
            "fusion",
        ):
            samples = sum((item.get("latencyMs") or {}).get(stage) is not None for item in results)
            availability[stage]["samples"] = samples
            if samples == 0 and (
                global_enabled
                or stage
                not in {
                    "globalRetrieval",
                    "globalDenseRetrieval",
                    "globalSparseRetrieval",
                    "globalEmbedding",
                    "merchantAggregation",
                    "hydration",
                    "fusion",
                }
            ):
                availability[stage] = {
                    "available": False,
                    "reason": "service did not expose this isolated stage timer",
                    "samples": 0,
                }
    return availability


def _index_action(args: argparse.Namespace) -> str:
    explicit = getattr(args, "index_action", None)
    legacy_reuse = bool(getattr(args, "reuse_index", False))
    if explicit and legacy_reuse and explicit != "reuse":
        raise ValueError("--reuse-index conflicts with --index-action build/resume.")
    return explicit or ("reuse" if legacy_reuse else "build")


async def _embedding_preflight(
    embedding: EmbeddingService,
    data_directory: Path,
    *,
    args: argparse.Namespace,
    suite: dict,
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if embedding.metadata.provider == "hash":
        return {
            "status": "not-required",
            "reason": "local deterministic provider",
            "documentCount": int(suite.get("indexedDocuments") or 0),
            "projectedCostUsd": 0.0,
        }
    sample_size = int(getattr(args, "preflight_sample_size", 100))
    corpus = corpus or _sample_corpus(data_directory, sample_size)
    _require_expected_corpus_size(corpus, suite)
    before_documents = embedding.usage_snapshot()
    await embedding.embed_documents(corpus["sampleTexts"])
    document_usage = embedding.usage_snapshot().delta(before_documents)
    if document_usage.total_tokens <= 0 or corpus["sampleCharacters"] <= 0:
        raise ValueError("Embedding provider did not report token usage during preflight.")

    query_examples = [
        "quiet vegan dinner near Midtown",
        "适合带轮椅长辈去的安静餐厅",
        "Queens family brunch with 无障碍入口",
    ]
    before_queries = embedding.usage_snapshot()
    for query in query_examples:
        await embedding.embed_query(query)
    query_usage = embedding.usage_snapshot().delta(before_queries)
    embedding.clear_query_cache()

    projected_document_tokens = math.ceil(
        corpus["totalCharacters"] * document_usage.total_tokens / corpus["sampleCharacters"] * 1.15
    )
    projected_query_tokens = math.ceil(
        query_usage.total_tokens / len(query_examples) * int(suite["caseCount"]) * 1.15
    )
    projected_tokens = projected_document_tokens + projected_query_tokens
    price = float(_price_per_million_tokens(args))
    projected_cost = projected_tokens / 1_000_000 * price
    cost_cap = float(getattr(args, "max_provider_cost_usd", 0.0) or 0.0)
    if projected_cost > cost_cap:
        raise ValueError(
            f"Projected embedding cost ${projected_cost:.4f} exceeds the configured "
            f"${cost_cap:.2f} hard cap; no index was modified."
        )
    return {
        "status": "passed",
        "sampleMethod": "sha256-minhash-v1",
        "sampleDocuments": len(corpus["sampleTexts"]),
        "sampleCharacters": corpus["sampleCharacters"],
        "sampleTokens": document_usage.total_tokens,
        "documentCount": corpus["documentCount"],
        "totalCharacters": corpus["totalCharacters"],
        "contentTypeCounts": corpus["contentTypeCounts"],
        "projectedDocumentTokensWith15PctMargin": projected_document_tokens,
        "projectedQueryTokensWith15PctMargin": projected_query_tokens,
        "projectedTotalTokens": projected_tokens,
        "priceUsdPerMillionTokens": price,
        "projectedCostUsd": projected_cost,
        "hardCostCapUsd": cost_cap,
        "providerUsage": embedding.usage_snapshot().as_dict(),
    }


def _sample_corpus(data_directory: Path, sample_size: int) -> dict[str, Any]:
    if sample_size < 1:
        raise ValueError("--preflight-sample-size must be positive.")
    sample: list[tuple[int, str, str]] = []
    document_count = 0
    total_characters = 0
    content_type_counts: dict[str, int] = {}
    for document in iter_generated_documents(data_directory):
        document_count += 1
        total_characters += len(document.text)
        content_type_counts[document.content_type] = content_type_counts.get(document.content_type, 0) + 1
        score = int.from_bytes(
            hashlib.sha256(document.document_id.encode("utf-8")).digest()[:8],
            "big",
        )
        item = (-score, document.document_id, document.text)
        if len(sample) < sample_size:
            heapq.heappush(sample, item)
        elif score < -sample[0][0]:
            heapq.heapreplace(sample, item)
    texts = [item[2] for item in sorted(sample, key=lambda item: (-item[0], item[1]))]
    return {
        "sampleTexts": texts,
        "sampleCharacters": sum(map(len, texts)),
        "documentCount": document_count,
        "totalCharacters": total_characters,
        "contentTypeCounts": dict(sorted(content_type_counts.items())),
    }


def _require_expected_corpus_size(corpus: dict[str, Any], suite: dict) -> None:
    expected = int(suite.get("indexedDocuments") or 0)
    actual = int(corpus.get("documentCount") or 0)
    if expected < 1:
        raise ValueError("A paid M1 suite must declare a positive indexedDocuments count.")
    if actual != expected:
        raise ValueError(
            f"Corpus generated {actual} documents, but the frozen suite requires {expected}; "
            "refusing any provider request."
        )


def _price_per_million_tokens(args: argparse.Namespace) -> float:
    selected = _selected_profile(args)
    if selected is None:
        return 0.0
    return selected.price_usd_per_million_tokens


def _provider_usage_report(usage: EmbeddingUsage, args: argparse.Namespace) -> dict[str, Any]:
    price = _price_per_million_tokens(args)
    return {
        **usage.as_dict(),
        "priceUsdPerMillionTokens": price,
        "estimatedCostUsd": usage.total_tokens / 1_000_000 * price,
        "hardCostCapUsd": float(getattr(args, "max_provider_cost_usd", 0.0) or 0.0),
    }


def _usage_from_dict(value: dict[str, Any]) -> EmbeddingUsage:
    defaults = EmbeddingUsage().as_dict()
    parsed: dict[str, int | float] = {}
    for key, default in defaults.items():
        raw = value.get(key, default)
        parsed[key] = float(raw) if isinstance(default, float) else int(raw)
        if parsed[key] < 0:
            raise ValueError("Embedding usage counters cannot be negative.")
    return EmbeddingUsage(**parsed)


def _merge_usage(*values: EmbeddingUsage) -> EmbeddingUsage:
    fields = EmbeddingUsage().as_dict()
    return EmbeddingUsage(**{key: sum(getattr(value, key) for value in values) for key in fields})


async def _wait_for_collection_ready(
    client: AsyncQdrantClient,
    collection: str,
    *,
    expected_points: int,
    timeout_seconds: float,
    require_server_ready: bool,
    visibility_filter: models.Filter | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        info = await client.get_collection(collection)
        count = int((await client.count(collection, exact=True)).count)
        status = _enum_value(getattr(info, "status", None))
        optimizer_status = _enum_value(getattr(info, "optimizer_status", None))
        indexed_vectors = int(getattr(info, "indexed_vectors_count", 0) or 0)
        sentinel_visible = expected_points == 0
        if count == expected_points and expected_points:
            visible, _ = await client.scroll(
                collection_name=collection,
                scroll_filter=visibility_filter,
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
            sentinel_visible = bool(visible)
        snapshot = {
            "status": status,
            "optimizerStatus": optimizer_status,
            "pointCount": count,
            "indexedVectorsCount": indexed_vectors,
            "indexedVectorsCountSemantics": "approximate-observation-only",
            "sentinelVisible": sentinel_visible,
            "expectedPointCount": expected_points,
        }
        count_ready = count == expected_points
        server_ready = status.casefold() in {"green", "ok"} and optimizer_status.casefold() in {"ok", "green"}
        if count_ready and sentinel_visible and (not require_server_ready or server_ready):
            return snapshot
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Qdrant collection did not become ready: {snapshot}")
        await asyncio.sleep(2.0)


async def _qdrant_server_metadata(location: str | Path) -> dict[str, Any]:
    value = str(location).rstrip("/")
    if not value.startswith(("http://", "https://")):
        return {"mode": _location_kind(location), "version": None}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{value}/")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"mode": "server", "version": None, "metadataAvailable": False}
    return {
        "mode": "server",
        "version": payload.get("version"),
        "commit": payload.get("commit"),
        "metadataAvailable": True,
    }


async def _require_qdrant_server_contract(location: str | Path) -> dict[str, Any]:
    if _location_kind(location) != "remote":
        return await _qdrant_server_metadata(location)
    metadata = await _qdrant_server_metadata(location)
    version = str(metadata.get("version") or "")
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (TypeError, ValueError):
        raise ValueError("Qdrant Server metadata/version is unavailable; refusing paid preflight.") from None
    if major != 1 or minor < 19:
        raise ValueError(f"M1 requires Qdrant Server 1.19+ in the 1.x series; observed {version!r}.")
    return metadata


def _require_reused_server_version(
    location: str | Path,
    manifest_path: Path,
    *,
    current_server: Mapping[str, Any],
) -> None:
    if _location_kind(location) != "remote":
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    indexed_server = manifest.get("qdrantServer") or {}
    current_version = _major_minor_version(current_server.get("version"))
    indexed_version = _major_minor_version(indexed_server.get("version"))
    if current_version is None or indexed_version is None:
        raise ValueError(
            "Qdrant Server major/minor metadata is missing from the current server or index manifest."
        )
    if current_version != indexed_version:
        raise ValueError(
            "Qdrant Server major/minor differs from the server that built the reused index: "
            f"current={current_server.get('version')!r}, indexed={indexed_server.get('version')!r}."
        )


def _major_minor_version(value: Any) -> tuple[int, int] | None:
    try:
        parts = str(value).split(".")
        return int(parts[0]), int(parts[1])
    except (IndexError, TypeError, ValueError):
        return None


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, dict):
        return "error" if raw.get("error") else "ok"
    if getattr(raw, "error", None):
        return "error"
    return str(raw or "unknown")


def _validate_feature_configuration(args: argparse.Namespace) -> None:
    if not 1 <= args.candidate_limit <= 10:
        raise ValueError("--candidate-limit must be between 1 and 10.")
    if not args.candidate_limit <= args.discovery_pool_size <= 100:
        raise ValueError("--discovery-pool-size must be between candidate limit and 100.")
    if not 8 <= args.embedding_dimensions <= 4096:
        raise ValueError("--embedding-dimensions must be between 8 and 4096.")
    if args.warmup_cases < 0:
        raise ValueError("--warmup-cases cannot be negative.")
    if args.limit_cases is not None and args.limit_cases < 1:
        raise ValueError("--limit-cases must be positive.")
    expected_enabled = args.global_retrieval_mode == "global-hybrid"
    if bool(args.global_retrieval_enabled) is not expected_enabled:
        raise ValueError(
            "--global-retrieval-mode and the explicit --global-retrieval-enabled flag "
            "must agree (global-hybrid requires the flag; candidate-filtered forbids it)."
        )
    if not 1 <= args.global_document_limit <= 500:
        raise ValueError("--global-document-limit must be between 1 and 500.")
    if not args.candidate_limit <= args.global_merchant_limit <= 200:
        raise ValueError("--global-merchant-limit must be between candidate limit and 200.")
    if args.global_document_limit < args.global_merchant_limit:
        raise ValueError("--global-document-limit must be at least global merchant limit.")
    if not 1 <= args.global_documents_per_merchant <= 10:
        raise ValueError("--global-documents-per-merchant must be between 1 and 10.")
    if args.global_documents_per_merchant > args.global_document_limit:
        raise ValueError("--global-documents-per-merchant cannot exceed global document limit.")
    if not 1 <= args.global_hydration_concurrency <= 64:
        raise ValueError("--global-hydration-concurrency must be between 1 and 64.")
    if not 0 < args.global_branch_timeout_seconds <= 120:
        raise ValueError("--global-branch-timeout-seconds must be in (0, 120].")
    if not 1 <= args.fusion_rrf_k <= 1_000:
        raise ValueError("--fusion-rrf-k must be between 1 and 1000.")
    if not 1 <= args.brand_cap <= args.candidate_limit:
        raise ValueError("--brand-cap must be between 1 and candidate limit.")
    if args.split == "test" and expected_enabled:
        raise ValueError("Global retrieval may not run against the consumed M1 policy holdout.")
    action = _index_action(args)
    if args.preflight_only and args.provider_smoke:
        raise ValueError("Choose either --preflight-only or --provider-smoke, not both.")
    if args.embedding_provider == "hash":
        if args.embedding_model not in (None, "deterministic-token-sha256"):
            raise ValueError(
                "The Hash provider implementation is fixed to --embedding-model deterministic-token-sha256."
            )
        if args.embedding_version not in (None, "hash-v1"):
            raise ValueError("The Hash provider implementation is fixed to --embedding-version hash-v1.")
    else:
        if _selected_profile(args) is None:
            raise ValueError(
                "Paid M1 evaluation requires --embedding-profile so model, dimensions, "
                "price, and cost cap cannot drift."
            )
        if args.embedding_dimensions != 1_024:
            raise ValueError("M1 paid embedding profiles are fixed to 1024 dimensions.")
        if _location_kind(args.qdrant_location) != "remote" and not (
            args.preflight_only or args.provider_smoke
        ):
            raise ValueError("M1 paid evaluation requires Qdrant Server via an HTTP(S) URL.")
        if action in {"build", "resume"} and not (
            args.allow_paid_index_build or args.preflight_only or args.provider_smoke
        ):
            raise ValueError("Paid index construction requires the explicit --allow-paid-index-build flag.")
        if args.limit_cases is not None and action in {"build", "resume"}:
            raise ValueError(
                "--limit-cases does not limit indexing and is forbidden during a paid build; "
                "use --provider-smoke before the full build."
            )
        if args.max_provider_cost_usd is None or args.max_provider_cost_usd <= 0:
            raise ValueError("Paid profiles require a positive provider cost cap.")
        if args.embedding_query_instruct:
            raise ValueError("The frozen M1 comparison does not enable a Qwen query instruction.")
        if args.split == "test" and not (args.preflight_only or args.provider_smoke):
            if action != "reuse":
                raise ValueError("The M1 policy holdout must reuse the selected Dev index.")
    supported = {
        "query_rewrite_provider": (args.query_rewrite_provider, "disabled"),
        "reranker_provider": (args.reranker_provider, "heuristic-multi-signal"),
    }
    for name, (actual, expected) in supported.items():
        if actual != expected:
            raise ValueError(
                f"M0 accepts {name} in the config snapshot but only supports {expected!r}; "
                f"received {actual!r}. Implement the stage before benchmarking it."
            )


def _validate_m1_policy_artifacts(
    args: argparse.Namespace,
    *,
    suite: dict[str, Any] | None = None,
) -> None:
    if args.embedding_provider == "hash" or args.preflight_only or args.provider_smoke:
        return
    if args.global_retrieval_mode == "global-hybrid" or int((suite or {}).get("schemaVersion") or 0) == 3:
        return
    if args.baseline_report is None:
        raise ValueError("Formal M1 evaluation requires the frozen Hash baseline via --baseline-report.")
    expected = {
        "quality gate": FROZEN_QUALITY_GATE_PATH,
        "Hash baseline": FROZEN_HASH_BASELINE_PATH,
    }
    actual = {
        "quality gate": args.quality_gate,
        "Hash baseline": args.baseline_report,
    }
    for label, expected_path in expected.items():
        actual_path = actual[label]
        if not actual_path.is_file():
            raise ValueError(f"Formal M1 {label} file does not exist: {actual_path}")
        if _file_sha256(actual_path) != _file_sha256(expected_path):
            raise ValueError(f"Formal M1 {label} must match the committed frozen artifact exactly.")


def _validate_m2_run_configuration(
    args: argparse.Namespace,
    *,
    suite: dict[str, Any],
    resolved_config: dict[str, Any],
    repository: Path,
    scoped_source: dict[str, Any] | None = None,
    runtime_environment: dict[str, str] | None = None,
) -> bool:
    schema_version = int(suite.get("schemaVersion") or 0)
    global_mode = args.global_retrieval_mode == "global-hybrid"
    capture_only = schema_version == 2 and global_mode
    if capture_only:
        validate_frozen_m1_dev_source_suite(suite)
        if args.candidate_universe_output is None:
            raise ValueError(
                "A schema-v2 global run is capture-only and requires --candidate-universe-output."
            )
        capture_outputs = {
            "candidate universe": args.candidate_universe_output,
            "report": args.output,
            "summary": args.summary_output,
        }
        resolved_outputs = [
            path.resolve() for path in capture_outputs.values() if path is not None
        ]
        if len(resolved_outputs) != len(set(resolved_outputs)):
            raise ValueError("M2 capture output, summary, and candidate-universe paths must be distinct.")
        for label, path in capture_outputs.items():
            if path is not None and path.exists():
                raise FileExistsError(f"Refusing to overwrite frozen M2 {label}: {path}")
        if args.limit_cases is not None:
            raise ValueError("M2 candidate-universe capture must run every Dev case.")
        if _index_action(args) != "reuse":
            raise ValueError("M2 candidate capture must reuse the selected M1 index.")
        return True

    if args.candidate_universe_output is not None:
        raise ValueError("--candidate-universe-output is only valid for a schema-v2 global capture.")
    if schema_version != 3:
        return False
    if suite.get("split") != "dev":
        raise ValueError("Schema-v3 M2 evaluation is Dev-only.")
    if args.output is None:
        raise ValueError("Formal M2 evaluation requires an explicit --output path.")
    protected_paths = {
        "report": args.output,
        "summary": args.summary_output,
        "baseline": args.baseline_report,
    }
    resolved_paths = [path.resolve() for path in protected_paths.values() if path is not None]
    if len(resolved_paths) != len(set(resolved_paths)):
        raise ValueError("M2 report, summary, and baseline paths must be distinct.")
    for label in ("report", "summary"):
        path = protected_paths[label]
        if path is not None and path.exists():
            raise FileExistsError(f"Refusing to overwrite frozen M2 {label}: {path}")
    if _file_sha256(args.quality_gate) != _file_sha256(M2_QUALITY_GATE_PATH):
        raise ValueError("Formal M2 evaluation must use the committed m2_quality_gate.json.")
    if _index_action(args) != "reuse":
        raise ValueError("Formal M2 control/treatment runs must reuse the exact M1 index.")
    contract = suite["judgmentContract"]
    if int(contract["candidateLimit"]) != args.candidate_limit:
        raise ValueError("M2 candidate limit differs from the bounded judgment contract.")
    experiment_fingerprint = _m2_experiment_fingerprint(resolved_config)
    if contract.get("experimentFingerprint") != experiment_fingerprint:
        raise ValueError("M2 runtime differs from the retrieval configuration used to capture judgments.")
    current_source = (scoped_source or _scoped_source_snapshot(repository))["sha256"]
    if contract.get("captureScopedSourceSha256") != current_source:
        raise ValueError(
            "M2 Eval/retrieval source changed after candidate capture; recapture and rebuild "
            "the bounded Dev suite."
        )
    if contract.get("captureRuntimeEnvironment") != (
        runtime_environment or _runtime_environment_snapshot()
    ):
        raise ValueError(
            "M2 Python/qdrant-client environment differs from candidate capture; recapture "
            "and rebuild the bounded Dev suite."
        )
    if global_mode and args.baseline_report is None:
        raise ValueError(
            "M2 global-hybrid treatment requires the candidate-filtered control report via --baseline-report."
        )
    if not global_mode and args.baseline_report is not None:
        raise ValueError("M2 candidate-filtered control must not use a baseline report.")
    return False


def _policy_artifact_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "qualityGateSha256": _file_sha256(args.quality_gate),
        "baselineReportSha256": (_file_sha256(args.baseline_report) if args.baseline_report else None),
    }


def _validate_holdout_authorization(
    args: argparse.Namespace,
    resolved_config: dict,
    *,
    suite: dict,
) -> None:
    if args.split != "test" or args.embedding_provider == "hash":
        return
    if not args.allow_policy_holdout or args.winner_manifest is None:
        raise ValueError("The M1 policy holdout requires --winner-manifest and --allow-policy-holdout.")
    if args.output is None:
        raise ValueError("The M1 policy holdout requires an explicit non-existing --output path.")
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite a frozen holdout report: {args.output}")
    winner = json.loads(args.winner_manifest.read_text(encoding="utf-8"))
    if winner.get("policyVersion") != POLICY_VERSION:
        raise ValueError("Winner manifest uses an unsupported policy version.")
    _verify_winner_manifest(args.winner_manifest, winner)
    _validate_holdout_source(winner)
    embedding = resolved_config["embedding"]
    if winner.get("winnerProfileId") != embedding.get("profileId"):
        raise ValueError("Only the preselected M1 winner may run on the policy holdout.")
    if winner.get("winnerEmbedding") != embedding:
        raise ValueError("Winner manifest embedding metadata does not match this run.")
    expected_artifacts = {
        "qualityGateSha256": _file_sha256(FROZEN_QUALITY_GATE_PATH),
        "baselineReportSha256": _file_sha256(FROZEN_HASH_BASELINE_PATH),
    }
    frozen_artifacts = winner.get("frozenArtifacts") or {}
    observed_artifacts = {
        "qualityGateSha256": ((frozen_artifacts.get("qualityGate") or {}).get("sha256")),
        "baselineReportSha256": ((frozen_artifacts.get("baselineManifest") or {}).get("sha256")),
    }
    if observed_artifacts != expected_artifacts:
        raise ValueError("Winner manifest does not bind the committed M1 policy artifacts.")
    expected_control = normalized_dev_control(resolved_config, include_collection=True)
    if winner.get("winnerDevControl") != expected_control:
        raise ValueError("Holdout retrieval, runtime, collection, or Qdrant endpoint drifted from Dev.")
    receipt_path = _holdout_receipt_path(args.winner_manifest, suite)
    if receipt_path.exists():
        raise FileExistsError(f"The M1 policy holdout has already been attempted: {receipt_path}")


def _holdout_receipt_path(winner_manifest: Path, suite: dict) -> Path:
    winner = json.loads(winner_manifest.read_text(encoding="utf-8"))
    selection_sha = _winner_selection_fingerprint(winner)[:16]
    suite_sha = str(suite.get("caseSha256") or "")[:16]
    return EVAL_DIRECTORY.parents[1] / ".local" / f"m1-holdout-{selection_sha}-{suite_sha}.json"


def _verify_winner_manifest(path: Path, winner: dict[str, Any]) -> None:
    references = winner.get("devReports")
    if not isinstance(references, dict) or set(references) != EXPECTED_PROFILES:
        raise ValueError("Winner manifest must bind exactly the three frozen M1 profiles.")
    report_paths: list[Path] = []
    for profile_id in sorted(EXPECTED_PROFILES):
        reference = references.get(profile_id)
        if not isinstance(reference, dict):
            raise ValueError(f"Winner manifest has an invalid Dev report for {profile_id}.")
        filename = reference.get("filename")
        expected_sha = reference.get("sha256")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or not _is_sha256_text(expected_sha)
        ):
            raise ValueError(f"Winner manifest has an invalid Dev report for {profile_id}.")
        report_path = path.parent / filename
        if not report_path.is_file() or _file_sha256(report_path) != expected_sha:
            raise ValueError(f"Winner Dev report is missing or changed for {profile_id}.")
        report_paths.append(report_path)

    recomputed = compare_m1_reports(report_paths)
    if set(winner) != set(recomputed):
        raise ValueError("Winner manifest fields do not match the frozen selection output.")
    for key, value in recomputed.items():
        if key != "generatedAt" and winner.get(key) != value:
            raise ValueError("Winner manifest does not match recomputation from its Dev reports.")


def _winner_selection_fingerprint(winner: dict[str, Any]) -> str:
    identity = {
        "policyVersion": winner.get("policyVersion"),
        "winnerProfileId": winner.get("winnerProfileId"),
        "winnerEmbeddingIdentity": (winner.get("winnerEmbedding") or {}).get("identity"),
        "winnerDevControlFingerprint": winner.get("winnerDevControlFingerprint"),
        "devScopedSourceSha256": winner.get("devScopedSourceSha256"),
        "frozenArtifacts": winner.get("frozenArtifacts"),
    }
    return _fingerprint(identity)


def _validate_holdout_source(winner: dict[str, Any]) -> None:
    repository = Path(__file__).resolve().parents[3]
    current = _scoped_source_snapshot(repository)["sha256"]
    if winner.get("devScopedSourceSha256") != current:
        raise ValueError("Holdout Eval source differs from the source frozen by Dev reports.")


def _is_sha256_text(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _reserve_holdout_receipt(
    args: argparse.Namespace,
    resolved_config: dict,
    suite: dict,
) -> Path | None:
    if args.split != "test" or args.embedding_provider == "hash":
        return None
    path = _holdout_receipt_path(args.winner_manifest, suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schemaVersion": 1,
        "state": "running",
        "startedAt": datetime.now(UTC).isoformat(),
        "winnerManifestSha256": _file_sha256(args.winner_manifest),
        "testCaseSha256": suite["caseSha256"],
        "testSuiteContractSha256": suite["suiteContractSha256"],
        "holdoutControlFingerprint": _fingerprint(
            normalized_dev_control(resolved_config, include_collection=True)
        ),
    }
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError:
        raise FileExistsError(f"The M1 policy holdout has already been attempted: {path}") from None
    return path


def _finalize_holdout_receipt(
    path: Path,
    *,
    state: str,
    report_sha256: str | None = None,
    error_type: str | None = None,
) -> None:
    if state not in {"complete", "failed"}:
        raise ValueError(f"Unsupported holdout receipt state: {state}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("state") != "running":
        raise ValueError("M1 holdout receipt is not in state=running.")
    value.update(
        {
            "state": state,
            "finishedAt": datetime.now(UTC).isoformat(),
            "reportSha256": report_sha256,
            "errorType": error_type,
        }
    )
    _write_json_atomic(path, value)


def _validate_cases(suite: dict) -> None:
    cases = suite["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Eval case IDs must be unique.")
    expected_languages = {"en": 40, "zh": 30, "mixed": 10}
    if suite.get("languageCounts") != expected_languages:
        raise ValueError(f"Eval split must contain {expected_languages}.")
    threshold = int(suite["binaryRelevanceThreshold"])
    for case in cases:
        if case.get("split") != suite["split"]:
            raise ValueError(f"Case {case.get('id')} is in the wrong split.")
        judgments = case.get("judgments") or []
        external_ids = [item.get("externalId") for item in judgments]
        if not judgments or len(external_ids) != len(set(external_ids)):
            raise ValueError(f"Case {case.get('id')} has missing or duplicate judgments.")
        if any(int(item.get("relevance", -1)) not in {0, 1, 2, 3} for item in judgments):
            raise ValueError(f"Case {case.get('id')} has an invalid relevance grade.")
        if not any(int(item["relevance"]) >= threshold for item in judgments):
            raise ValueError(f"Case {case.get('id')} has no relevant judgments.")
        for negative in case.get("hardNegatives") or []:
            if not negative.get("hardConstraintViolations"):
                raise ValueError(f"Case {case.get('id')} has a hard negative without violations.")
        if case.get("language") == "mixed":
            terms = (case.get("metadata") or {}).get("codeSwitchTerms") or []
            if not terms or not any(term in case["query"] for term in terms):
                raise ValueError(f"Mixed case {case.get('id')} lacks explicit code-switch terms.")


def _validate_m2_judgment_contract(
    directory: Path,
    suite: dict[str, Any],
    *,
    trusted_source_suite: dict[str, Any] | None = None,
) -> None:
    if suite.get("suite") != M2_SUITE_NAME or suite.get("split") != "dev":
        raise ValueError("Schema-v3 M2 evaluation is Dev-only and uses the dedicated M2 suite.")
    contract = suite.get("judgmentContract") or {}
    if contract.get("policyVersion") != M2_JUDGMENT_POLICY_VERSION:
        raise ValueError("M2 suite uses an unsupported judgment policy.")
    if contract.get("unjudgedReturnedPolicy") != "fail-closed":
        raise ValueError("M2 suite must fail closed on every unjudged returned merchant.")
    if contract.get("sourceSplit") != "dev" or contract.get("m1PolicyHoldoutUsed") is not False:
        raise ValueError("M2 suite may not derive judgments from the consumed M1 policy holdout.")
    committed_dev = (
        frozen_m1_dev_source_identity()
        if trusted_source_suite is None
        else {
            "suite": trusted_source_suite.get("suite"),
            "caseSha256": trusted_source_suite.get("caseSha256"),
            "suiteContractSha256": trusted_source_suite.get("suiteContractSha256"),
        }
    )
    contract_dev = {
        "suite": contract.get("sourceSuite"),
        "caseSha256": contract.get("sourceSuiteCaseSha256"),
        "suiteContractSha256": contract.get("sourceSuiteContractSha256"),
    }
    if contract_dev != committed_dev:
        raise ValueError("M2 judgment contract is not derived from the committed M1 Dev suite.")
    fixture_name = contract.get("candidateUniverseFixture")
    if fixture_name != M2_CANDIDATE_UNIVERSE_FILENAME or Path(str(fixture_name)).name != fixture_name:
        raise ValueError("M2 suite references an invalid candidate-universe fixture.")
    fixture_path = directory / fixture_name
    if not fixture_path.is_file():
        raise ValueError(f"M2 suite requires its sibling {fixture_name} fixture.")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual_fixture_sha = m2_candidate_universe_sha256(fixture)
    if (
        fixture.get("fixtureSha256") != actual_fixture_sha
        or contract.get("candidateUniverseFixtureSha256") != actual_fixture_sha
    ):
        raise ValueError("M2 candidate-universe fixture SHA does not match the suite contract.")
    expected_fixture_fields = {
        "split": "dev",
        "sourceSuite": contract.get("sourceSuite"),
        "sourceSuiteCaseSha256": contract.get("sourceSuiteCaseSha256"),
        "sourceSuiteContractSha256": contract.get("sourceSuiteContractSha256"),
        "dataVersion": suite["dataVersion"],
        "datasetSha256": suite["datasetSha256"],
        "retrievalMode": "global-hybrid",
        "globalRetrievalEnabled": True,
        "candidateLimit": int(contract.get("candidateLimit") or 0),
        "experimentFingerprint": contract.get("experimentFingerprint"),
        "configFingerprint": contract.get("captureConfigFingerprint"),
        "indexManifestFingerprint": contract.get("captureIndexManifestFingerprint"),
        "scopedSourceSha256": contract.get("captureScopedSourceSha256"),
        "runtimeEnvironment": contract.get("captureRuntimeEnvironment"),
        "qdrantServer": contract.get("captureQdrantServer"),
        "caseCount": int(suite["caseCount"]),
    }
    for field, expected in expected_fixture_fields.items():
        if fixture.get(field) != expected:
            raise ValueError(f"M2 candidate-universe {field} differs from the suite contract.")

    universe_by_case = {str(item["id"]): item for item in fixture.get("cases") or []}
    if list(universe_by_case) != [str(case["id"]) for case in suite["cases"]]:
        raise ValueError("M2 candidate-universe case order/IDs differ from the suite.")
    structured_pairs = 0
    bounded_pairs = 0
    qdrant_only_pairs = 0
    relevant_miss_pairs = 0
    threshold = int(suite["binaryRelevanceThreshold"])
    for case in suite["cases"]:
        metadata = case.get("metadata") or {}
        structured = list(metadata.get("structuredCandidateExternalIds") or [])
        treatment = list(metadata.get("treatmentReturnedExternalIds") or [])
        fixture_treatment = list(universe_by_case[str(case["id"])]["returnedExternalIds"])
        if treatment != fixture_treatment:
            raise ValueError(f"M2 case {case['id']} differs from its captured treatment output.")
        if len(structured) != len(set(structured)) or len(treatment) != len(set(treatment)):
            raise ValueError(f"M2 case {case['id']} has duplicate candidate-universe IDs.")
        judged = {str(item["externalId"]): item for item in case["judgments"]}
        expected_qdrant_only = sorted(set(treatment) - set(structured))
        if not set(structured) | set(treatment) <= judged.keys():
            raise ValueError(f"M2 case {case['id']} does not label its bounded candidate union.")
        if metadata.get("qdrantOnlyJudgmentExternalIds") != expected_qdrant_only:
            raise ValueError(f"M2 case {case['id']} has inconsistent Qdrant-only judgments.")
        if int(metadata.get("boundedJudgmentCount") or 0) != len(judged):
            raise ValueError(f"M2 case {case['id']} has an invalid bounded judgment count.")
        if len(judged) > len(structured) + int(contract["candidateLimit"]):
            raise ValueError(f"M2 case {case['id']} exceeds the bounded-union contract.")
        for external_id, judgment in judged.items():
            expected_origin = (
                "structured-candidate-pool"
                if external_id in set(structured)
                else "observed-global-treatment-output"
            )
            if judgment.get("judgmentOrigin") != expected_origin:
                raise ValueError(f"M2 case {case['id']} has an invalid judgment origin.")
            relevant_miss_pairs += (
                external_id not in set(structured) and int(judgment["relevance"]) >= threshold
            )
        structured_pairs += len(structured)
        bounded_pairs += len(judged)
        qdrant_only_pairs += len(expected_qdrant_only)

    expected_counts = {
        "structuredJudgmentPairs": structured_pairs,
        "boundedJudgmentPairs": bounded_pairs,
        "observedTreatmentPairs": int(fixture["candidatePairCount"]),
        "qdrantOnlyJudgmentPairs": qdrant_only_pairs,
        "binaryRelevantStructuredMissPairs": relevant_miss_pairs,
    }
    for field, expected in expected_counts.items():
        if int(contract.get(field) or 0) != expected:
            raise ValueError(f"M2 judgment contract {field} is inconsistent.")
    if qdrant_only_pairs < 1 or relevant_miss_pairs < 1:
        raise ValueError("M2 suite does not exercise a relevant structured-miss rescue.")
    if int(contract.get("fullCartesianPairsAvoided") or 0) <= 0:
        raise ValueError("M2 suite must document avoidance of the full corpus Cartesian product.")


def _load_baseline(path: Path | None, *, split: str) -> dict | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if all(field in value for field in ("suite", "run", "summary")):
        _validate_baseline_report(value)
        return value
    frozen_split = (value.get("splits") or {}).get(split)
    if frozen_split is None:
        raise ValueError(f"Frozen baseline manifest has no {split!r} split.")
    if frozen_split.get("qualityGatePassed") is not True:
        raise ValueError("Frozen baseline split did not pass its quality gate.")
    case_count = int(frozen_split.get("caseCount") or 0)
    if case_count < 1:
        raise ValueError("Frozen baseline split is missing a positive caseCount.")
    latency_fingerprint = frozen_split.get("latencyProfileFingerprint")
    if not latency_fingerprint:
        raise ValueError("Frozen baseline split is missing latencyProfileFingerprint.")
    overall = frozen_split.get("overall") or {}
    by_language = {
        language: {"ndcgAt10": score}
        for language, score in (frozen_split.get("languageNdcgAt10") or {}).items()
    }
    latency = frozen_split.get("latencyMs") or {}
    return {
        "suite": {
            "split": split,
            "caseCount": case_count,
            "caseSha256": frozen_split.get("caseSha256"),
            "suiteContractSha256": frozen_split.get("suiteContractSha256"),
        },
        "run": {
            "latencyProfileFingerprint": latency_fingerprint,
            "evaluatedCases": case_count,
            "partial": False,
        },
        "summary": {
            "overall": overall,
            "byLanguage": by_language,
            "integrity": frozen_split.get("integrity") or {},
            "latencyMs": {
                "total": {
                    "p50": latency.get("totalP50"),
                    "p95": latency.get("totalP95"),
                    "p99": latency.get("totalP99"),
                }
            },
        },
    }


def _validate_baseline_report(report: dict) -> None:
    suite = report.get("suite") or {}
    run = report.get("run") or {}
    case_count = int(suite.get("caseCount") or 0)
    evaluated = int(run.get("evaluatedCases") or 0)
    if bool(run.get("partial")) or not case_count or evaluated != case_count:
        raise ValueError("Baseline report must be a complete run with evaluatedCases equal to caseCount.")
    if not run.get("latencyProfileFingerprint"):
        raise ValueError("Baseline report is missing latencyProfileFingerprint.")
    quality_gate = report.get("qualityGate")
    if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
        raise ValueError("Baseline report must have passed its quality gate.")


def _validate_adversarial_fixture(directory: Path, suite: dict) -> None:
    path = directory / "adversarial_documents.json"
    if not path.is_file():
        raise ValueError("Eval suite requires its sibling adversarial_documents.json fixture.")
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if int(fixture.get("schemaVersion") or 0) != 1:
        raise ValueError("Adversarial fixture must use schemaVersion=1.")
    if fixture.get("dataVersion") != suite["dataVersion"]:
        raise ValueError("Adversarial fixture dataVersion does not match the eval suite.")
    if fixture.get("datasetSha256") != suite["datasetSha256"]:
        raise ValueError("Adversarial fixture datasetSha256 does not match the eval suite.")
    actual_sha = fixture_contract_sha256(fixture)
    if fixture.get("fixtureSha256") != actual_sha:
        raise ValueError("Adversarial fixture SHA does not match its canonical document list.")
    if suite.get("adversarialFixtureSha256") != actual_sha:
        raise ValueError("Eval suite points to a different adversarial fixture SHA.")


def _qdrant_client(location: str | Path) -> AsyncQdrantClient:
    value = str(location)
    if value.startswith(("http://", "https://")):
        return AsyncQdrantClient(url=value)
    if value == ":memory:":
        return AsyncQdrantClient(location=value)
    return AsyncQdrantClient(path=value)


def _vector_dimensions(info: Any) -> int:
    vectors = info.config.params.vectors
    dense = vectors.get("dense") if isinstance(vectors, dict) else vectors
    size = getattr(dense, "size", None)
    if size is None:
        raise ValueError("Collection does not expose a dense vector dimension.")
    return int(size)


def _index_schema_snapshot(info: Any) -> dict[str, Any]:
    params = info.config.params
    dense = params.vectors.get("dense") if isinstance(params.vectors, Mapping) else None
    sparse = params.sparse_vectors.get("lexical") if isinstance(params.sparse_vectors, Mapping) else None
    snapshot = {
        "dense": {
            "name": "dense",
            "dimensions": int(getattr(dense, "size", 0) or 0),
            "distance": _enum_value(getattr(dense, "distance", "")),
        },
        "sparse": {
            "name": "lexical",
            "modifier": _enum_value(getattr(sparse, "modifier", "")),
        },
    }
    payload_schema = getattr(info, "payload_schema", None)
    if isinstance(payload_schema, Mapping) and payload_schema:
        snapshot["payloadIndexes"] = {
            field: _enum_value(getattr(payload_schema.get(field), "data_type", payload_schema.get(field)))
            for field in sorted(REQUIRED_PAYLOAD_INDEXES)
        }
    return snapshot


def _expected_index_schema(
    dimensions: int,
    *,
    include_payload_indexes: bool = False,
) -> dict[str, Any]:
    expected = {
        "dense": {
            "name": "dense",
            "dimensions": dimensions,
            "distance": _enum_value(models.Distance.COSINE),
        },
        "sparse": {
            "name": "lexical",
            "modifier": _enum_value(models.Modifier.IDF),
        },
    }
    if include_payload_indexes:
        expected["payloadIndexes"] = {
            field: _enum_value(schema) for field, schema in sorted(REQUIRED_PAYLOAD_INDEXES.items())
        }
    return expected


def _require_expected_index_schema(
    info: Any,
    dimensions: int,
    *,
    require_payload_indexes: bool = False,
) -> None:
    actual = _index_schema_snapshot(info)
    if not require_payload_indexes:
        actual.pop("payloadIndexes", None)
    expected = _expected_index_schema(
        dimensions,
        include_payload_indexes=require_payload_indexes,
    )
    if actual != expected:
        raise ValueError(f"Existing collection schema {actual!r} does not match expected {expected!r}.")


def _default_index_manifest(location: str | Path, collection: str) -> Path:
    value = str(location)
    if value.startswith(("http://", "https://")):
        endpoint = _endpoint_fingerprint(value)[:16]
        collection_id = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:12]
        return EVAL_DIRECTORY.parents[1] / ".local" / f"rag-v2-remote-index-{endpoint}-{collection_id}.json"
    if value == ":memory:":
        collection_id = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:12]
        return EVAL_DIRECTORY.parents[1] / ".local" / f"rag-v2-memory-{collection_id}.json"
    return Path(f"{value}.rag-v2-index-manifest.json")


def _manifest_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return _fingerprint(value)


def _directory_size(raw_path: str | Path) -> int | None:
    value = str(raw_path)
    path = Path(value)
    if value.startswith(("http://", "https://")) or value == ":memory:" or not path.exists():
        return None
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _location_kind(location: str | Path) -> str:
    value = str(location)
    if value.startswith(("http://", "https://")):
        return "remote"
    if value == ":memory:":
        return "memory"
    return "local-disk"


def _endpoint_fingerprint(location: str | Path) -> str:
    normalized = str(location).rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _git_snapshot(repository: Path) -> dict[str, Any]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
    )
    return {"sha": sha or None, "dirty": dirty}


def _scoped_source_snapshot(repository: Path) -> dict[str, Any]:
    snapshot = _file_set_fingerprint(repository, EVAL_SOURCE_PATHS)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *EVAL_SOURCE_PATHS],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {
        **snapshot,
        "dirty": bool(status),
    }


def _same_scoped_source_snapshot(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    return before.get("sha256") == after.get("sha256") and before.get(
        "fileSha256"
    ) == after.get("fileSha256")


def _runtime_environment_snapshot() -> dict[str, str]:
    return {
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "qdrantClientVersion": importlib.metadata.version("qdrant-client"),
    }


def _file_set_fingerprint(repository: Path, relative_paths: tuple[str, ...]) -> dict[str, Any]:
    file_sha256: dict[str, str] = {}
    for relative_path in relative_paths:
        path = repository / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Fingerprint source file is missing: {relative_path}")
        file_sha256[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "sha256": _fingerprint(file_sha256),
        "fileCount": len(file_sha256),
        "fileSha256": file_sha256,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latency_profile_fingerprint(config: dict) -> str:
    value = {
        "qdrant": config["qdrant"],
        "eval": config["eval"],
        "retrieval": config["retrieval"],
        "embedding": config["embedding"],
        "features": config["features"],
    }
    return _fingerprint(value)


def _m2_experiment_fingerprint(config: dict[str, Any]) -> str:
    """Bind every control except the single M2 feature under test."""

    value = json.loads(json.dumps(config))
    value.pop("experimentControlFingerprint", None)
    (value.get("retrieval") or {}).pop("mode", None)
    features = value.get("features") or {}
    features.pop("globalRetrievalMode", None)
    features.pop("globalRetrievalEnabled", None)
    return _fingerprint(value)


def _evaluation_manifest(
    *,
    suite: dict[str, Any],
    resolved_config: dict[str, Any],
    config_fingerprint: str,
    experiment_fingerprint: str,
    scoped_source: dict[str, Any],
    runtime_environment: dict[str, str],
    index_report: dict[str, Any],
    candidate_universe: dict[str, Any] | None,
) -> dict[str, Any]:
    judgment_contract = suite.get("judgmentContract")
    return {
        "version": "rag-v2-eval-manifest-v2",
        "suiteSchemaVersion": int(suite["schemaVersion"]),
        "suiteContractSha256": suite["suiteContractSha256"],
        "caseSha256": suite["caseSha256"],
        "judgmentContractSha256": (sha256_json(judgment_contract) if judgment_contract else None),
        "candidateUniverseFixtureSha256": (
            candidate_universe.get("fixtureSha256")
            if candidate_universe
            else (judgment_contract or {}).get("candidateUniverseFixtureSha256")
        ),
        "configFingerprint": config_fingerprint,
        "m2ExperimentFingerprint": experiment_fingerprint,
        "scopedSourceSha256": scoped_source.get("sha256"),
        "runtimeEnvironmentFingerprint": _fingerprint(runtime_environment),
        "indexManifestFingerprint": index_report.get("manifestFingerprint"),
        "qdrantServerFingerprint": _fingerprint(index_report.get("qdrantServer") or {}),
        "embeddingIdentity": (resolved_config.get("embedding") or {}).get("identity"),
        "retrievalMode": (resolved_config.get("retrieval") or {}).get("mode"),
        "globalRetrievalEnabled": (resolved_config.get("features") or {}).get("globalRetrievalEnabled"),
    }


def _candidate_capture_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "capture": {
            "caseCount": len(results),
            "returnedCandidatePairs": sum(item["returnedCount"] for item in results),
            "unjudgedCandidatePairs": sum(int(item["metrics"]["unjudgedReturnedCount"]) for item in results),
            "qdrantOnlyMerchantObservations": sum(
                int((item.get("retrievalTrace") or {}).get("qdrantOnlyMerchants") or 0) for item in results
            ),
        }
    }


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _path(value: dict, path: str) -> Any:
    current: Any = value
    for segment in path.split("."):
        current = current[segment]
    return current


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError:
        raise FileExistsError(f"Refusing to overwrite frozen artifact: {path}") from None


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    repository = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Run the frozen RAG v2 quality and latency baseline.")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--quality-gate", type=Path, default=EVAL_DIRECTORY / "quality_gate.json")
    parser.add_argument(
        "--data-directory",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p13-full",
    )
    parser.add_argument(
        "--qdrant-location",
        default=str(repository / "agent-service" / ".local" / "qdrant-p13-v5-8b645404"),
    )
    parser.add_argument("--collection", default="hmdp_content_v2")
    parser.add_argument("--index-manifest", type=Path)
    parser.add_argument("--index-batch-size", type=int, default=128)
    parser.add_argument("--reuse-index", action="store_true")
    parser.add_argument("--index-action", choices=("reuse", "build", "resume"))
    parser.add_argument("--allow-paid-index-build", action="store_true")
    parser.add_argument(
        "--embedding-profile",
        choices=tuple(PROFILES),
        help="Frozen provider/model/dimension/price profile for comparable M1 runs.",
    )
    parser.add_argument("--embedding-provider", choices=("hash", "openai", "qwen"), default="hash")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-version")
    parser.add_argument("--embedding-dimensions", type=int, default=64)
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--embedding-max-concurrency", type=int, default=2)
    parser.add_argument("--embedding-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--embedding-max-retries", type=int, default=4)
    parser.add_argument("--embedding-max-batch-characters", type=int, default=250_000)
    parser.add_argument("--embedding-query-cache-size", type=int, default=512)
    parser.add_argument("--embedding-query-cache-ttl-seconds", type=float, default=900.0)
    parser.add_argument("--embedding-query-instruct", default="")
    parser.add_argument("--max-provider-cost-usd", type=float)
    parser.add_argument("--preflight-sample-size", type=int, default=100)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--provider-smoke", action="store_true")
    parser.add_argument("--qdrant-ready-timeout-seconds", type=float, default=1_800.0)
    parser.add_argument("--query-rewrite-provider", default="disabled")
    parser.add_argument(
        "--global-retrieval-mode",
        choices=("candidate-filtered", "global-hybrid"),
        default="candidate-filtered",
    )
    parser.add_argument(
        "--global-retrieval-enabled",
        action="store_true",
        help="Explicit treatment flag; required together with --global-retrieval-mode global-hybrid.",
    )
    parser.add_argument("--global-document-limit", type=int, default=200)
    parser.add_argument("--global-merchant-limit", type=int, default=60)
    parser.add_argument("--global-documents-per-merchant", type=int, default=3)
    parser.add_argument("--global-hydration-concurrency", type=int, default=8)
    parser.add_argument("--global-branch-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--fusion-rrf-k", type=int, default=60)
    parser.add_argument("--brand-cap", type=int, default=2)
    parser.add_argument("--reranker-provider", default="heuristic-multi-signal")
    parser.add_argument("--discovery-pool-size", type=int, default=100)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--warmup-cases", type=int, default=1)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--winner-manifest", type=Path)
    parser.add_argument("--allow-policy-holdout", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--candidate-universe-output", type=Path)
    parser.add_argument("--no-fail", action="store_true")
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    _, passed = await run(args)
    if not passed and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
