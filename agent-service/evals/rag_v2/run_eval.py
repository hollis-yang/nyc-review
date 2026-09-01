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
from app.rag.lexical import canonical_tags
from app.rag.nyc_loader import iter_generated_documents
from app.rag.qdrant_store import REQUIRED_PAYLOAD_INDEXES, QdrantRagService
from app.rag.query_batching import embed_query_batch
from app.rag.query_rewriter import (
    PROMPT_VERSION,
    DisabledQueryRewriter,
    OpenAICompatibleQueryRewriter,
    QueryRewriteProvider,
)
from app.rag.reranker import (
    DEFAULT_RERANKER_VERSION,
    CandidateReranker,
    HttpCrossEncoderReranker,
    MerchantRerankTextBuilder,
)
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
from evals.rag_v2.build_m3_cases import (
    FROZEN_M2_DEV_SUITE_PATH,
    M3_CANDIDATE_UNIVERSE_FILENAME,
    M3_JUDGMENT_POLICY_VERSION,
    M3_SELECTION_LEAKAGE_WARNING,
    M3_SUITE_NAME,
    m3_candidate_universe_sha256,
    m3_experiment_fingerprint,
    rewrite_config_fingerprint,
    validate_frozen_m2_dev_source_suite,
)
from evals.rag_v2.build_m4_cases import (
    M4_CANDIDATE_UNIVERSE_FILENAME,
    M4_JUDGMENT_POLICY_VERSION,
    M4_SELECTION_LEAKAGE_WARNING,
    M4_SUITE_NAME,
    m4_candidate_universe_sha256,
    m4_experiment_fingerprint,
    reranker_config_fingerprint,
    validate_frozen_m3_dev_source_suite,
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
M3_QUALITY_GATE_PATH = EVAL_DIRECTORY / "m3_quality_gate.json"
M4_QUALITY_GATE_PATH = EVAL_DIRECTORY / "m4_quality_gate.json"
M3_PRICING_SNAPSHOT_DATE = "2026-09-01"
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
    "agent-service/app/rag/query_batching.py",
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
M3_EVAL_SOURCE_PATHS = (
    *EVAL_SOURCE_PATHS,
    "agent-service/app/rag/query_rewriter.py",
    "agent-service/evals/rag_v2/build_m3_cases.py",
    "agent-service/evals/rag_v2/compare_m3.py",
    "agent-service/evals/rag_v2/m3_quality_gate.json",
)
M4_EVAL_SOURCE_PATHS = (
    *M3_EVAL_SOURCE_PATHS,
    "agent-service/app/rag/reranker.py",
    "agent-service/evals/rag_v2/build_m4_cases.py",
    "agent-service/evals/rag_v2/compare_m4.py",
    "agent-service/evals/rag_v2/m4_quality_gate.json",
)
_M3_REWRITE_SAFETY_REASONS = frozenset(
    {
        "hard-constraint-mismatch",
        "input-too-long",
        "invalid-response",
        "language-mismatch",
        "negation-mismatch",
        "negation-not-preserved",
        "required-tag-mismatch",
        "too-many-rewrites",
    }
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

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            vectors = await embed_query_batch(self._inner, texts)
            if vectors is None:
                return await asyncio.gather(
                    *(self._inner.embed_query(text) for text in texts)
                )
            return vectors
        finally:
            self.query_calls += len(texts)
            self.texts += len(texts)
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
    if schema_version not in {2, 3, 4, 5}:
        raise ValueError("RAG v2 suite must use schemaVersion=2, 3, 4, or 5.")
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
    elif schema_version == 4:
        _validate_m3_judgment_contract(path.parent, suite)
    elif schema_version == 5:
        _validate_m4_judgment_contract(path.parent, suite)

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
    allow_unjudged: bool = False,
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
            "candidateRankingLatencyMs",
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
    m3_enabled = bool(getattr(runtime, "m3_enabled", False))
    rewrite_usage = _rewrite_case_usage(
        discovery_metadata,
        enabled=m3_enabled,
        input_price_usd_per_million_tokens=float(
            getattr(runtime, "rewrite_input_price_usd_per_million_tokens", 0.0)
        ),
        output_price_usd_per_million_tokens=float(
            getattr(runtime, "rewrite_output_price_usd_per_million_tokens", 0.0)
        ),
    )
    m4_enabled = bool(getattr(runtime, "m4_enabled", False))
    reranker_usage = _reranker_case_usage(
        discovery_metadata,
        enabled=m4_enabled,
    )

    external_ids = [candidate.external_id for candidate in ranked.candidates]
    judgments = {str(item["externalId"]): item for item in case["judgments"]}
    unjudged_external_ids = sorted(
        {str(external_id) for external_id in external_ids if str(external_id) not in judgments}
    )
    judgment_contract = suite.get("judgmentContract") or {}
    if (
        judgment_contract.get("unjudgedReturnedPolicy") == "fail-closed"
        and unjudged_external_ids
        and not allow_unjudged
    ):
        raise ValueError(
            f"Bounded Eval case {case['id']} returned merchants outside its judgment union: "
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
    semantic_rule_coverage = _semantic_rule_coverage(case)
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
        "semanticRuleCoverage": semantic_rule_coverage,
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
            "queryRewrite": _timing_value(
                discovery_metadata,
                "queryRewrite",
                "queryRewriteLatencyMs",
            ),
            "reranker": _timing_value(
                discovery_metadata,
                "reranker",
                "rerankerLatencyMs",
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
            "rewriteRequests": int(getattr(runtime, "query_rewriter", None) is not None),
            "rerankerRequests": int(
                m4_enabled and bool(discovery_metadata.get("rerankerEnabled"))
            ),
            "providerUsage": embedding["providerUsage"],
            **({"rewriteProviderUsage": rewrite_usage} if m3_enabled else {}),
            **(
                {
                    "rerankerProviderUsage": reranker_usage,
                    "rerankerFallback": bool(
                        discovery_metadata.get("rerankerFallback", False)
                    ),
                }
                if m4_enabled
                else {}
            ),
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


def _semantic_rule_coverage(case: Mapping[str, Any]) -> str | None:
    """Separate true rule misses from semantic queries already helped by aliases."""

    if case.get("scenario") != "semantic_alias_composition":
        return None
    query = str(case.get("query") or "")
    preference_tags = {
        str(tag) for tag in (case.get("preferenceTags") or []) if isinstance(tag, str)
    }
    recognized = set(canonical_tags(query)) & preference_tags
    return "ruleCovered" if recognized else "outOfDictionary"


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


def _rewrite_case_usage(
    metadata: Mapping[str, Any],
    *,
    enabled: bool,
    input_price_usd_per_million_tokens: float,
    output_price_usd_per_million_tokens: float,
) -> dict[str, int | float]:
    if not enabled:
        return {
            "network_requests": 0,
            "total_tokens": 0,
            "retry_count": 0,
            "failure_count": 0,
            "query_cache_hits": 0,
            "estimated_cost_usd": 0.0,
        }

    def counter(name: str) -> int:
        value = metadata.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"M3 retrieval metadata {name} must be a non-negative integer.")
        return value

    network_requests = counter("queryRewriteNetworkRequests")
    input_tokens = counter("queryRewriteInputTokens")
    output_tokens = counter("queryRewriteOutputTokens")
    estimated_cost = (
        input_tokens * input_price_usd_per_million_tokens
        + output_tokens * output_price_usd_per_million_tokens
    ) / 1_000_000
    return {
        "network_requests": network_requests,
        "total_tokens": input_tokens + output_tokens,
        "retry_count": 0,
        "failure_count": int(bool(metadata.get("queryRewriteFallback", False))),
        "query_cache_hits": int(bool(metadata.get("queryRewriteCacheHit", False))),
        "estimated_cost_usd": float(estimated_cost),
    }


def _reranker_case_usage(
    metadata: Mapping[str, Any],
    *,
    enabled: bool,
) -> dict[str, int | float]:
    """Normalize Candidate Discovery's stable M4 trace into report counters."""

    if not enabled:
        return {
            "network_requests": 0,
            "total_tokens": 0,
            "retry_count": 0,
            "failure_count": 0,
            "cache_hits": 0,
            "estimated_cost_usd": 0.0,
        }

    def counter(*names: str) -> int:
        value: Any = 0
        for name in names:
            if name in metadata:
                value = metadata[name]
                break
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"M4 retrieval metadata {'/'.join(names)} must be a non-negative integer."
            )
        return value

    estimated_cost = metadata.get("rerankerEstimatedCostUsd", 0.0)
    if (
        isinstance(estimated_cost, bool)
        or not isinstance(estimated_cost, (int, float))
        or not math.isfinite(float(estimated_cost))
        or float(estimated_cost) < 0
    ):
        raise ValueError("M4 rerankerEstimatedCostUsd must be finite and non-negative.")
    return {
        "network_requests": counter("rerankerNetworkRequests"),
        "total_tokens": counter("rerankerTokens"),
        "retry_count": counter("rerankerRetryCount", "rerankerRetries"),
        "failure_count": counter("rerankerFailureCount", "rerankerFailures"),
        "cache_hits": int(bool(metadata.get("rerankerCacheHit", False))),
        "estimated_cost_usd": float(estimated_cost),
    }


def _retrieval_trace(
    metadata: Mapping[str, Any],
    *,
    structured_count: int,
    returned_count: int,
) -> dict[str, Any]:
    enabled = bool(metadata.get("globalRetrievalEnabled"))
    structured_external_ids = metadata.get("structuredBranchExternalIds")
    if isinstance(structured_external_ids, tuple):
        structured_external_ids = list(structured_external_ids)

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
        "structuredBranchCandidates": count(
            len(structured_external_ids) if isinstance(structured_external_ids, list) else 0,
            "structuredBranchCandidates",
        ),
        "structuredBranchExternalIds": structured_external_ids,
        "structuredCandidates": count(structured_count, "structuredCandidates"),
        "globalDenseDocuments": count(0, "globalDenseDocuments", "denseDocuments", "denseReturned"),
        "globalSparseDocuments": count(0, "globalSparseDocuments", "sparseDocuments", "sparseReturned"),
        "globalDenseReturnedPoints": count(0, "globalDenseReturnedPoints"),
        "globalSparseReturnedPoints": count(0, "globalSparseReturnedPoints"),
        "globalDenseRejectedPoints": count(0, "globalDenseRejectedPoints"),
        "globalSparseRejectedPoints": count(0, "globalSparseRejectedPoints"),
        "globalMerchants": count(0, "globalMerchants"),
        "fusionCandidates": count(returned_count, "fusionCandidates"),
        "fusionPoolCandidates": count(returned_count, "fusionPoolCandidates"),
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
        "candidateRankingFallback": bool(metadata.get("candidateRankingFallback")),
        "candidateRankingFallbackReason": metadata.get("candidateRankingFallbackReason"),
        "globalQueryVariantPartialFailureIds": list(
            metadata.get("globalQueryVariantPartialFailureIds") or []
        ),
        "globalQueryVariantTimedOutIds": list(
            metadata.get("globalQueryVariantTimedOutIds") or []
        ),
        "globalQueryVariantFailedIds": list(
            metadata.get("globalQueryVariantFailedIds") or []
        ),
        "queryRewriteEnabled": bool(metadata.get("queryRewriteEnabled")),
        "queryRewriteFallback": bool(metadata.get("queryRewriteFallback")),
        "queryRewriteFallbackReason": metadata.get("queryRewriteFallbackReason"),
        "preRerankCandidateExternalIds": list(
            metadata.get("preRerankCandidateExternalIds") or []
        ),
        "preRerankPoolFingerprint": metadata.get("preRerankPoolFingerprint"),
        "rerankerInputExternalIds": list(
            metadata.get("rerankerInputExternalIds") or []
        ),
        "rerankerInputFingerprint": metadata.get("rerankerInputFingerprint"),
        "rerankerInputDocumentIds": dict(
            metadata.get("rerankerInputDocumentIds") or {}
        ),
        "rerankerEnabled": bool(metadata.get("rerankerEnabled")),
        "rerankerProvider": metadata.get("rerankerProvider"),
        "rerankerModel": metadata.get("rerankerModel"),
        "rerankerModelVersion": metadata.get("rerankerModelVersion"),
        "rerankerStatus": metadata.get("rerankerStatus"),
        "rerankerCandidates": count(0, "rerankerCandidates"),
        "rerankerLatencyMs": _timing_value(metadata, "rerankerLatencyMs", "reranker"),
        "rerankerNetworkRequests": count(0, "rerankerNetworkRequests"),
        "rerankerTokens": count(0, "rerankerTokens"),
        "rerankerEstimatedCostUsd": metadata.get("rerankerEstimatedCostUsd", 0.0),
        "rerankerRetryCount": count(0, "rerankerRetryCount", "rerankerRetries"),
        "rerankerFailureCount": count(
            0, "rerankerFailureCount", "rerankerFailures"
        ),
        "rerankerFallback": bool(metadata.get("rerankerFallback")),
        "rerankerFallbackReason": metadata.get("rerankerFallbackReason"),
        "rerankerCacheHit": bool(metadata.get("rerankerCacheHit")),
        "rerankerCircuitState": metadata.get("rerankerCircuitState"),
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


def _raise_m3_case_runtime_failure(result: Mapping[str, Any]) -> None:
    """Abort immediately so a broken provider contract cannot consume the full budget."""

    trace = result.get("retrievalTrace") or {}
    if trace.get("queryRewriteFallback"):
        reason = trace.get("queryRewriteFallbackReason") or "unknown"
        raise ValueError(
            f"M3 case {result.get('id')} used query rewrite fallback ({reason}); aborting."
        )
    failed_variants = sorted(
        {
            str(variant_id)
            for field in (
                "globalQueryVariantPartialFailureIds",
                "globalQueryVariantTimedOutIds",
                "globalQueryVariantFailedIds",
            )
            for variant_id in (trace.get(field) or [])
        }
    )
    if failed_variants:
        raise ValueError(
            f"M3 case {result.get('id')} had incomplete query variants: "
            + ", ".join(failed_variants)
        )


def _raise_m4_case_runtime_failure(
    result: Mapping[str, Any],
    *,
    learned_treatment: bool,
    expected_case: Mapping[str, Any] | None = None,
) -> None:
    """Fail formal/capture evidence closed on incomplete pools or reranker fallback."""

    trace = result.get("retrievalTrace") or {}
    case_id = str(result.get("id") or "unknown")
    pool_ids = trace.get("preRerankCandidateExternalIds")
    if (
        not isinstance(pool_ids, list)
        or not pool_ids
        or len(pool_ids) > 30
        or any(not isinstance(item, str) or not item for item in pool_ids)
        or len(pool_ids) != len(set(pool_ids))
    ):
        raise ValueError(f"M4 case {case_id} has an invalid pre-rerank Top-30 pool.")
    if trace.get("preRerankPoolFingerprint") != sha256_json(pool_ids):
        raise ValueError(f"M4 case {case_id} has an invalid pre-rerank pool fingerprint.")
    input_fingerprint = trace.get("rerankerInputFingerprint")
    if not isinstance(input_fingerprint, str) or len(input_fingerprint) != 64:
        raise ValueError(f"M4 case {case_id} is missing its reranker input fingerprint.")
    if expected_case is not None:
        expected = expected_case.get("metadata") or {}
        if (
            pool_ids != expected.get("preRerankCandidateExternalIds")
            or trace.get("preRerankPoolFingerprint")
            != expected.get("preRerankPoolFingerprint")
            or input_fingerprint != expected.get("rerankerInputFingerprint")
        ):
            raise ValueError(
                f"M4 case {case_id} did not replay its frozen pre-rerank pool/input."
            )
    if trace.get("rerankerFallback"):
        reason = trace.get("rerankerFallbackReason") or "unknown"
        raise ValueError(f"M4 case {case_id} used reranker fallback ({reason}); aborting.")
    if int(trace.get("rerankerRetryCount") or 0) != 0 or int(
        trace.get("rerankerFailureCount") or 0
    ) != 0:
        raise ValueError(f"M4 case {case_id} observed a reranker retry or failure.")
    if learned_treatment and (
        trace.get("rerankerEnabled") is not True
        or trace.get("rerankerStatus") != "applied"
        or int(trace.get("rerankerCandidates") or 0) != len(pool_ids)
        or int(trace.get("rerankerNetworkRequests") or 0) != 1
    ):
        raise ValueError(
            f"M4 case {case_id} requires exactly one successful learned reranker batch."
        )


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
    schema_version = int(suite.get("schemaVersion") or 0)
    m4_run = bool(getattr(args, "m4_capture", False) or schema_version == 5)
    m3_run = not m4_run and bool(
        getattr(args, "m3_capture_arm", None) or schema_version == 4
    )
    rewrite_run = m3_run or m4_run
    m2_run = not rewrite_run and (schema_version == 3 or (
        int(suite.get("schemaVersion") or 0) == 2
        and args.global_retrieval_mode == "global-hybrid"
    ))
    initial_scoped_source = (
        _m4_scoped_source_snapshot(repository)
        if m4_run
        else _m3_scoped_source_snapshot(repository)
        if m3_run
        else (_scoped_source_snapshot(repository) if m2_run else None)
    )
    if m4_run:
        capture_only = _validate_m4_run_configuration(
            args,
            suite=suite,
            resolved_config=resolved_config,
            repository=repository,
            scoped_source=initial_scoped_source,
            runtime_environment=runtime_environment,
        )
    elif m3_run:
        capture_only = _validate_m3_run_configuration(
            args,
            suite=suite,
            resolved_config=resolved_config,
            repository=repository,
            scoped_source=initial_scoped_source,
            runtime_environment=runtime_environment,
        )
    else:
        capture_only = _validate_m2_run_configuration(
            args,
            suite=suite,
            resolved_config=resolved_config,
            repository=repository,
            scoped_source=initial_scoped_source,
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
        allow_unjudged_capture = bool(
            capture_only
            and (
                getattr(args, "m3_capture_arm", None) == "treatment"
                or getattr(args, "m4_capture", False)
            )
        )
        warmup_results = []
        for warmup_case in cases[: args.warmup_cases]:
            warmup_results.append(await evaluate_case(
                runtime,
                warmup_case,
                suite,
                candidate_limit=args.candidate_limit,
                capture_only=capture_only,
                allow_unjudged=allow_unjudged_capture,
            ))
        warmup_rewrite_cost = _rewrite_cost_from_results(warmup_results)
        warmup_reranker_cost = _reranker_cost_from_results(warmup_results)
        runtime.embedding_service.clear_query_cache()
        query_rewriter = getattr(runtime, "query_rewriter", None)
        if query_rewriter is not None:
            query_rewriter.clear_cache()
            query_rewriter.reset()
        reranker = getattr(runtime, "reranker", None)
        if reranker is not None:
            reranker.clear_cache()
            reranker.reset()

        results = []
        for index, case in enumerate(cases, start=1):
            result = await evaluate_case(
                runtime,
                case,
                suite,
                candidate_limit=args.candidate_limit,
                capture_only=capture_only,
                allow_unjudged=allow_unjudged_capture,
            )
            results.append(result)
            if rewrite_run:
                _raise_m3_case_runtime_failure(result)
                _require_rewrite_cost_within_cap(
                    warmup_rewrite_cost + _rewrite_cost_from_results(results),
                    resolved_config,
                )
            if m4_run:
                _raise_m4_case_runtime_failure(
                    result,
                    learned_treatment=args.reranker_provider == "qwen",
                    expected_case=None if capture_only else case,
                )
                _require_reranker_cost_within_cap(
                    warmup_reranker_cost + _reranker_cost_from_results(results),
                    resolved_config,
                )
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

        # Formal M3 evidence is serialized at six decimals. Freeze result rows
        # before aggregation so repeated per-case cost/metric rounding cannot
        # accumulate into a summary that the comparator cannot reproduce.
        if rewrite_run:
            results = rounded(results)

        if capture_only:
            summary = _candidate_capture_summary(results)
            quality_gate = {
                "passed": True,
                "failures": [],
                "warnings": [
                    "Candidate-universe capture is intentionally not scored; build the "
                    f"schema-{'v5' if m4_run else 'v4' if m3_run else 'v3'} Dev suite "
                    "before comparing quality."
                ],
                "relativeStatus": "not-applicable-candidate-capture",
                "thresholds": {},
            }
        else:
            summary = (
                _summarize_m4_results(results)
                if m4_run
                else summarize_results(results)
            )
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
            for name in (
                "structuredFallback",
                "globalFallback",
                "candidateRankingFallback",
            )
        )
        retrieval_fallback_count += sum(
            (result.get("retrievalTrace") or {}).get(name) is False
            for result in results
            if (result.get("retrievalTrace") or {}).get("globalRetrievalEnabled")
            for name in ("globalDenseAvailable", "globalSparseAvailable")
        )
        query_variant_failure_count = sum(
            len(
                {
                    str(variant_id)
                    for field in (
                        "globalQueryVariantPartialFailureIds",
                        "globalQueryVariantTimedOutIds",
                        "globalQueryVariantFailedIds",
                    )
                    for variant_id in ((result.get("retrievalTrace") or {}).get(field) or [])
                }
            )
            for result in results
        )
        retrieval_fallback_count += query_variant_failure_count
        identity_conflict_count = sum(
            int((result.get("retrievalTrace") or {}).get("identityConflicts") or 0) for result in results
        )
        retrieval_safety_issues = _m2_retrieval_safety_issues(results)
        retrieval_safety_rejection_count = sum(retrieval_safety_issues.values())
        rewrite_fallback_count = sum(
            bool((result.get("retrievalTrace") or {}).get("queryRewriteFallback"))
            for result in results
        )
        rewrite_safety_rejection_count = sum(
            (result.get("retrievalTrace") or {}).get("queryRewriteFallbackReason")
            in _M3_REWRITE_SAFETY_REASONS
            for result in results
        )
        reranker_fallback_count = sum(
            bool((result.get("retrievalTrace") or {}).get("rerankerFallback"))
            for result in results
        )
        reranker_retry_count = sum(
            int((result.get("retrievalTrace") or {}).get("rerankerRetryCount") or 0)
            for result in results
        )
        reranker_failure_count = sum(
            int((result.get("retrievalTrace") or {}).get("rerankerFailureCount") or 0)
            for result in results
        )
        if args.embedding_provider != "hash" and fallback_count:
            quality_gate["failures"].append(
                f"Formal embedding evaluation observed {fallback_count} sparse fallbacks."
            )
            quality_gate["passed"] = False
        bounded_run = capture_only or schema_version in {3, 4, 5}
        if bounded_run and retrieval_fallback_count:
            quality_gate["failures"].append(
                f"Bounded Eval observed {retrieval_fallback_count} retrieval/ranking fallbacks."
            )
            quality_gate["passed"] = False
        if bounded_run and identity_conflict_count:
            quality_gate["failures"].append(
                f"Bounded Eval rejected {identity_conflict_count} merchants with conflicting identities."
            )
            quality_gate["passed"] = False
        if bounded_run and retrieval_safety_rejection_count:
            quality_gate["failures"].append(
                "Bounded Eval observed incomplete hydration, identity mismatches, rejected global "
                f"points: {retrieval_safety_issues}."
            )
            quality_gate["passed"] = False
        if rewrite_run and rewrite_fallback_count:
            quality_gate["failures"].append(
                f"M3 observed {rewrite_fallback_count} query rewrite fallbacks."
            )
            quality_gate["passed"] = False
        if rewrite_run and rewrite_safety_rejection_count:
            quality_gate["failures"].append(
                f"M3 observed {rewrite_safety_rejection_count} rewrite safety rejections."
            )
            quality_gate["passed"] = False
        if m4_run and (
            reranker_fallback_count or reranker_retry_count or reranker_failure_count
        ):
            quality_gate["failures"].append(
                "M4 observed reranker fallback/retry/failure counts: "
                f"{reranker_fallback_count}/{reranker_retry_count}/{reranker_failure_count}."
            )
            quality_gate["passed"] = False
        if capture_only and not quality_gate["passed"]:
            raise ValueError(
                "Candidate capture observed a fallback, identity problem, incomplete "
                "hydration, or rejected global point; refusing to freeze an incomplete "
                "judgment universe."
            )
        final_scoped_source = (
            _m4_scoped_source_snapshot(repository)
            if m4_run
            else _m3_scoped_source_snapshot(repository)
            if m3_run
            else _scoped_source_snapshot(repository)
        )
        if initial_scoped_source is not None and not _same_scoped_source_snapshot(
            initial_scoped_source,
            final_scoped_source,
        ):
            raise ValueError(
                "Eval/retrieval source changed while the run was in progress; refusing "
                "to freeze or compare results from mixed source revisions."
            )
        scoped_source = initial_scoped_source or final_scoped_source
        config_fingerprint = _fingerprint(resolved_config)
        experiment_fingerprint = (
            m4_experiment_fingerprint(resolved_config)
            if m4_run
            else m3_experiment_fingerprint(resolved_config)
            if m3_run
            else _m2_experiment_fingerprint(resolved_config)
        )
        rewrite_fingerprint = (
            rewrite_config_fingerprint(resolved_config) if rewrite_run else None
        )
        prompt_fingerprint = (
            (resolved_config.get("queryRewrite") or {}).get("promptFingerprint")
            if rewrite_run
            else None
        )
        scored_rewrite_cost = _rewrite_cost_from_results(results)
        rewrite_provider_cost = {
            "scoredEstimatedCostUsd": float(scored_rewrite_cost),
            "warmupEstimatedCostUsd": float(warmup_rewrite_cost),
            "estimatedCostUsd": float(scored_rewrite_cost + warmup_rewrite_cost),
            "hardCostCapUsd": float(
                (resolved_config.get("queryRewrite") or {}).get(
                    "maxProviderCostUsd",
                    0.0,
                )
            ),
        }
        scored_reranker_cost = _reranker_cost_from_results(results)
        reranker_provider_cost = {
            "scoredEstimatedCostUsd": float(scored_reranker_cost),
            "warmupEstimatedCostUsd": float(warmup_reranker_cost),
            "estimatedCostUsd": float(scored_reranker_cost + warmup_reranker_cost),
            "hardCostCapUsd": float(
                (resolved_config.get("reranker") or {}).get(
                    "maxProviderCostUsd", 0.0
                )
            ),
        }
        git_snapshot = _git_snapshot(repository)
        candidate_universe = None
        if capture_only and not rewrite_run:
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
        if schema_version in {3, 4, 5}:
            suite_report["judgmentContractSha256"] = sha256_json(suite["judgmentContract"])
            suite_report["judgmentContract"] = suite["judgmentContract"]
        report = {
            "schemaVersion": (3 if capture_only and not rewrite_run else schema_version),
            "generatedAt": datetime.now(UTC).isoformat(),
            "mode": (
                "m4-pre-rerank-candidate-capture"
                if m4_run and capture_only
                else f"m3-candidate-universe-capture-{args.m3_capture_arm}"
                if m3_run and capture_only
                else ("m2-candidate-universe-capture" if capture_only else "evaluation")
            ),
            "suite": suite_report,
            "run": {
                "git": git_snapshot,
                "scopedSource": scoped_source,
                "runtimeEnvironment": runtime_environment,
                "configFingerprint": config_fingerprint,
                **(
                    {
                        "m4ExperimentFingerprint": experiment_fingerprint,
                        "rerankerConfigFingerprint": reranker_config_fingerprint(
                            resolved_config
                        ),
                        "rewriteConfigFingerprint": rewrite_fingerprint,
                        "promptFingerprint": prompt_fingerprint,
                        "rewriteProviderCost": rewrite_provider_cost,
                        "rerankerProviderCost": reranker_provider_cost,
                    }
                    if m4_run
                    else {
                        "m3ExperimentFingerprint": experiment_fingerprint,
                        "rewriteConfigFingerprint": rewrite_fingerprint,
                        "promptFingerprint": prompt_fingerprint,
                        "rewriteProviderCost": rewrite_provider_cost,
                    }
                    if m3_run
                    else {"m2ExperimentFingerprint": experiment_fingerprint}
                ),
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
                **(
                    {
                        "rewriteFallbackCount": rewrite_fallback_count,
                        "rewriteSafetyRejectionCount": rewrite_safety_rejection_count,
                    }
                    if rewrite_run
                    else {}
                ),
                **(
                    {
                        "rerankerFallbackCount": reranker_fallback_count,
                        "rerankerRetryCount": reranker_retry_count,
                        "rerankerFailureCount": reranker_failure_count,
                    }
                    if m4_run
                    else {}
                ),
            },
            "evaluationManifest": _evaluation_manifest(
                suite=suite,
                resolved_config=resolved_config,
                config_fingerprint=config_fingerprint,
                experiment_fingerprint=experiment_fingerprint,
                scoped_source=scoped_source,
                source_git=git_snapshot,
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
        frozen_m2_artifact = capture_only or schema_version in {3, 4, 5}
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
        if int(suite.get("schemaVersion") or 0) in {3, 4, 5}:
            expected_manifest = suite["judgmentContract"].get(
                "captureIndexManifestFingerprint"
            )
            if index_report["manifestFingerprint"] != expected_manifest:
                raise ValueError(
                    "Bounded Eval index manifest differs from the one used to capture its "
                    "candidate universe."
                )
            if suite["judgmentContract"].get("captureQdrantServer") != current_qdrant_server:
                raise ValueError(
                    "Qdrant Server metadata differs from candidate capture; recapture "
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
    query_rewriter: QueryRewriteProvider | None = None
    reranker: CandidateReranker | None = None

    async def close() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        await _close_eval_resources(
            embedding,
            client,
            query_rewriter=query_rewriter,
            reranker=reranker,
        )

    try:
        query_rewriter = _query_rewriter(args, resolved_config)
        reranker = _reranker(args, resolved_config)
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
                fusion_pool_limit=args.fusion_pool_limit,
                hydration_concurrency=args.global_hydration_concurrency,
                branch_timeout_seconds=args.global_branch_timeout_seconds,
                documents_per_merchant=args.global_documents_per_merchant,
                rrf_k=args.fusion_rrf_k,
                brand_cap=args.brand_cap,
                query_rewriter=query_rewriter,
                reranker=reranker,
                rerank_text_builder=MerchantRerankTextBuilder(
                    max_characters=int(
                        (resolved_config.get("reranker") or {}).get(
                            "inputBuilder", {}
                        ).get("maxDocumentCharacters", 1_600)
                    ),
                    max_evidence=int(
                        (resolved_config.get("reranker") or {}).get(
                            "inputBuilder", {}
                        ).get("maxEvidenceExcerpts", 2)
                    ),
                    max_evidence_characters=int(
                        (resolved_config.get("reranker") or {}).get(
                            "inputBuilder", {}
                        ).get("maxEvidenceCharacters", 500)
                    ),
                ),
                reranker_candidate_limit=int(
                    (resolved_config.get("reranker") or {}).get(
                        "candidateLimit", args.fusion_pool_limit
                    )
                ),
            )
        else:
            candidate_discovery = LegacyCandidateDiscovery(shop_service, rag)
    except BaseException:
        await _close_eval_resources(
            embedding,
            client,
            query_rewriter=query_rewriter,
            reranker=reranker,
            suppress_errors=True,
        )
        raise

    return SimpleNamespace(
        shop_service=shop_service,
        rag_service=rag,
        candidate_discovery=candidate_discovery,
        embedding_service=embedding,
        query_rewriter=query_rewriter,
        reranker=reranker,
        m3_enabled=bool(
            getattr(args, "m3_capture_arm", None)
            or getattr(args, "m4_capture", False)
            or int(suite.get("schemaVersion") or 0) in {4, 5}
        ),
        m4_enabled=bool(
            getattr(args, "m4_capture", False)
            or int(suite.get("schemaVersion") or 0) == 5
        ),
        rewrite_input_price_usd_per_million_tokens=float(
            (resolved_config.get("queryRewrite") or {}).get(
                "inputPriceUsdPerMillionTokens",
                0.0,
            )
        ),
        rewrite_output_price_usd_per_million_tokens=float(
            (resolved_config.get("queryRewrite") or {}).get(
                "outputPriceUsdPerMillionTokens",
                0.0,
            )
        ),
        index_report=index_report,
        prior_provider_usage=prior_provider_usage,
        close=close,
    )


async def _close_eval_resources(
    embedding: TimedEmbeddingService,
    client: AsyncQdrantClient,
    *,
    query_rewriter: QueryRewriteProvider | None = None,
    reranker: CandidateReranker | None = None,
    suppress_errors: bool = False,
) -> None:
    errors: list[BaseException] = []
    closes = [embedding.aclose, client.close]
    if reranker is not None:
        closes.insert(0, reranker.aclose)
    if query_rewriter is not None:
        closes.insert(0, query_rewriter.aclose)
    for close in closes:
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


def _query_rewriter(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> QueryRewriteProvider | None:
    rewrite = config.get("queryRewrite") or {}
    if rewrite.get("enabled") is not True:
        return None
    settings = _eval_settings()
    provider = str(rewrite["provider"])
    dedicated_key = settings.query_rewrite_api_key.get_secret_value()
    if provider == "openai":
        api_key = dedicated_key or settings.openai_embedding_api_key.get_secret_value()
    else:
        api_key = dedicated_key or settings.model_api_key
    if not api_key.strip():
        raise ValueError(f"M3 {provider} query rewrite requires a configured API key.")
    fallback = DisabledQueryRewriter(prompt_version=str(rewrite["promptVersion"]))
    runtime = rewrite["runtime"]
    base_url, _ = _query_rewrite_provider_values(args)
    return OpenAICompatibleQueryRewriter(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=str(rewrite["model"]),
        fallback=fallback,
        prompt_version=str(rewrite["promptVersion"]),
        max_queries=int(rewrite["maxQueries"]),
        timeout_seconds=float(runtime["timeoutSeconds"]),
        max_concurrency=int(runtime["maxConcurrency"]),
        cache_size=int(runtime["cacheSize"]),
        cache_ttl_seconds=float(runtime["cacheTtlSeconds"]),
        max_input_characters=int(runtime["maxInputCharacters"]),
        max_output_tokens=int(runtime["maxOutputTokens"]),
    )


def _reranker(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> CandidateReranker | None:
    reranker = config.get("reranker") or {}
    if reranker.get("enabled") is not True:
        return None
    if reranker.get("provider") != "qwen":
        raise ValueError("M4 Eval currently supports only the qwen learned reranker.")
    settings = _eval_settings()
    api_key = (
        settings.reranker_api_key.get_secret_value()
        or settings.qwen_embedding_api_key.get_secret_value()
    )
    if not api_key.strip():
        raise ValueError("M4 qwen reranking requires a configured reranker/DashScope API key.")
    base_url, _ = _reranker_provider_values(args)
    runtime = reranker["runtime"]
    instruction = _resolved_reranker_instruction(args)
    if hashlib.sha256(instruction.encode("utf-8")).hexdigest() != reranker.get(
        "instructionSha256"
    ):
        raise ValueError("M4 runtime instruction differs from resolved reranker config.")
    return HttpCrossEncoderReranker(
        provider="qwen",
        base_url=base_url,
        api_key=api_key,
        model=str(reranker["model"]),
        instruct=instruction,
        version=str(reranker["version"]),
        timeout_seconds=float(runtime["timeoutSeconds"]),
        max_concurrency=int(runtime["maxConcurrency"]),
        max_candidates=int(reranker["candidateLimit"]),
        max_retries=int(runtime["maxRetries"]),
        cache_size=int(runtime["cacheSize"]),
        cache_ttl_seconds=float(runtime["cacheTtlSeconds"]),
        circuit_failure_threshold=int(runtime["circuitFailureThreshold"]),
        circuit_recovery_seconds=float(runtime["circuitCooldownSeconds"]),
        input_cost_per_million_tokens=float(
            reranker["inputPriceUsdPerMillionTokens"]
        ),
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


def _query_rewrite_provider_values(args: argparse.Namespace) -> tuple[str, str]:
    provider = str(getattr(args, "query_rewrite_provider", "disabled"))
    if provider == "disabled":
        return "", "disabled"
    settings = _eval_settings()
    configured_base = str(getattr(args, "query_rewrite_base_url", "") or "")
    configured_model = str(getattr(args, "query_rewrite_model", "") or "")
    if provider == "openai":
        return (
            configured_base or settings.query_rewrite_base_url or "https://api.openai.com/v1",
            configured_model or settings.query_rewrite_model or "gpt-4o-mini-2024-07-18",
        )
    return (
        configured_base or settings.query_rewrite_base_url or settings.model_base_url,
        configured_model or settings.query_rewrite_model or settings.model_name,
    )


def _resolved_query_rewrite_config(
    args: argparse.Namespace,
    repository: Path,
) -> dict[str, Any]:
    provider = str(getattr(args, "query_rewrite_provider", "disabled"))
    enabled = provider != "disabled"
    if not enabled:
        return {
            "enabled": False,
            "provider": "disabled",
            "model": "disabled",
            "endpointFingerprint": None,
            "promptVersion": "disabled",
            "promptFingerprint": None,
            "maxQueries": 0,
            "inputPriceUsdPerMillionTokens": 0.0,
            "outputPriceUsdPerMillionTokens": 0.0,
            "pricingSnapshotDate": M3_PRICING_SNAPSHOT_DATE,
            "maxProviderCostUsd": float(
                getattr(args, "query_rewrite_max_provider_cost_usd", 0.1)
            ),
            "runtime": {
                "timeoutSeconds": float(
                    getattr(args, "query_rewrite_timeout_seconds", 8.0)
                ),
                "maxConcurrency": int(
                    getattr(args, "query_rewrite_max_concurrency", 2)
                ),
                "cacheSize": int(getattr(args, "query_rewrite_cache_size", 512)),
                "cacheTtlSeconds": float(
                    getattr(args, "query_rewrite_cache_ttl_seconds", 900.0)
                ),
                "maxInputCharacters": int(
                    getattr(args, "query_rewrite_max_input_characters", 2_000)
                ),
                "maxOutputTokens": int(
                    getattr(args, "query_rewrite_max_output_tokens", 300)
                ),
            },
        }

    base_url, model = _query_rewrite_provider_values(args)
    prompt_version = str(
        getattr(args, "query_rewrite_prompt_version", PROMPT_VERSION)
    ).strip()
    prompt_source = repository / "agent-service/app/rag/query_rewriter.py"
    prompt_fingerprint = _fingerprint(
        {
            "promptVersion": prompt_version,
            "queryRewriterSourceSha256": _file_sha256(prompt_source),
        }
    )
    return {
        "enabled": True,
        "provider": provider,
        "model": model,
        "endpointFingerprint": _endpoint_fingerprint(base_url),
        "promptVersion": prompt_version,
        "promptFingerprint": prompt_fingerprint,
        "maxQueries": int(getattr(args, "query_rewrite_max_queries", 3)),
        "inputPriceUsdPerMillionTokens": float(
            getattr(args, "query_rewrite_input_price_usd_per_million_tokens", 0.0)
        ),
        "outputPriceUsdPerMillionTokens": float(
            getattr(args, "query_rewrite_output_price_usd_per_million_tokens", 0.0)
        ),
        "pricingSnapshotDate": M3_PRICING_SNAPSHOT_DATE,
        "maxProviderCostUsd": float(
            getattr(args, "query_rewrite_max_provider_cost_usd", 0.1)
        ),
        "runtime": {
            "timeoutSeconds": float(
                getattr(args, "query_rewrite_timeout_seconds", 8.0)
            ),
            "maxConcurrency": int(
                getattr(args, "query_rewrite_max_concurrency", 2)
            ),
            "cacheSize": int(getattr(args, "query_rewrite_cache_size", 512)),
            "cacheTtlSeconds": float(
                getattr(args, "query_rewrite_cache_ttl_seconds", 900.0)
            ),
            "maxInputCharacters": int(
                getattr(args, "query_rewrite_max_input_characters", 2_000)
            ),
            "maxOutputTokens": int(
                getattr(args, "query_rewrite_max_output_tokens", 300)
            ),
        },
    }


def _reranker_provider_values(args: argparse.Namespace) -> tuple[str, str]:
    provider = str(getattr(args, "reranker_provider", "heuristic-multi-signal"))
    if provider == "heuristic-multi-signal":
        return "", "heuristic-multi-signal"
    if provider != "qwen":
        raise ValueError(f"Unsupported M4 reranker provider: {provider!r}.")
    settings = _eval_settings()
    configured_base = str(getattr(args, "reranker_base_url", "") or "").strip()
    base_url = configured_base or settings.reranker_base_url.strip()
    if not base_url:
        embedding_base = settings.qwen_embedding_base_url.strip().rstrip("/")
        suffix = "/compatible-mode/v1"
        if embedding_base.endswith("/compatible-api/v1"):
            base_url = embedding_base
        elif embedding_base.endswith(suffix):
            base_url = f"{embedding_base[: -len(suffix)]}/compatible-api/v1"
        else:
            raise ValueError(
                "M4 qwen reranking requires --reranker-base-url or a configured "
                "Qwen embedding URL ending in /compatible-mode/v1."
            )
    model = str(
        getattr(args, "reranker_model", "") or settings.reranker_model or "qwen3-rerank"
    )
    return base_url.rstrip("/"), model


def _resolved_reranker_config(
    args: argparse.Namespace,
    repository: Path,
) -> dict[str, Any]:
    provider = str(getattr(args, "reranker_provider", "heuristic-multi-signal"))
    enabled = provider != "heuristic-multi-signal"
    base_url, model = _reranker_provider_values(args)
    settings = _eval_settings()
    instruction = _resolved_reranker_instruction(args)
    instruction_version = str(
        getattr(args, "reranker_instruction_version", "m4-reranker-instruction-v1")
    ).strip()
    if not instruction_version:
        raise ValueError("M4 reranker instruction version cannot be blank.")
    input_version = str(
        getattr(args, "reranker_input_version", "merchant-rerank-text-v1")
    )
    max_characters = int(
        getattr(
            args,
            "reranker_max_document_characters",
            settings.reranker_max_document_characters,
        )
    )
    max_evidence = int(
        getattr(args, "reranker_max_evidence_excerpts", settings.reranker_max_evidence_excerpts)
    )
    max_evidence_characters = int(
        getattr(
            args,
            "reranker_max_evidence_characters",
            settings.reranker_max_evidence_characters,
        )
    )
    builder_contract = {
        "inputVersion": input_version,
        "sourceSha256": _file_sha256(
            repository / "agent-service/app/rag/reranker.py"
        ),
        "maxDocumentCharacters": max_characters,
        "maxEvidenceExcerpts": max_evidence,
        "maxEvidenceCharacters": max_evidence_characters,
    }
    return {
        "enabled": enabled,
        "provider": provider,
        "model": model,
        "version": str(
            getattr(args, "reranker_version", "")
            or (model if enabled else DEFAULT_RERANKER_VERSION)
        ),
        "endpointFingerprint": _endpoint_fingerprint(base_url) if enabled else None,
        "instructionVersion": instruction_version,
        "instructionSha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "inputVersion": input_version,
        "inputBuilderFingerprint": sha256_json(builder_contract),
        "inputBuilder": builder_contract,
        "candidateLimit": int(getattr(args, "reranker_candidate_limit", 30)),
        "inputPriceUsdPerMillionTokens": float(
            getattr(
                args,
                "reranker_input_price_usd_per_million_tokens",
                settings.reranker_input_price_usd_per_million_tokens,
            )
        ),
        "pricingSnapshotDate": M3_PRICING_SNAPSHOT_DATE,
        "maxProviderCostUsd": float(
            getattr(args, "reranker_max_provider_cost_usd", 0.5)
        ),
        "runtime": {
            "timeoutSeconds": float(
                getattr(args, "reranker_timeout_seconds", settings.reranker_timeout_seconds)
            ),
            "maxConcurrency": int(
                getattr(args, "reranker_max_concurrency", settings.reranker_max_concurrency)
            ),
            "maxRetries": int(
                getattr(args, "reranker_max_retries", settings.reranker_max_retries)
            ),
            "cacheSize": int(
                getattr(args, "reranker_cache_size", settings.reranker_cache_size)
            ),
            "cacheTtlSeconds": float(
                getattr(
                    args,
                    "reranker_cache_ttl_seconds",
                    settings.reranker_cache_ttl_seconds,
                )
            ),
            "circuitFailureThreshold": int(
                getattr(
                    args,
                    "reranker_circuit_failure_threshold",
                    settings.reranker_circuit_failure_threshold,
                )
            ),
            "circuitCooldownSeconds": float(
                getattr(
                    args,
                    "reranker_circuit_cooldown_seconds",
                    settings.reranker_circuit_cooldown_seconds,
                )
            ),
        },
    }


def _resolved_reranker_instruction(args: argparse.Namespace) -> str:
    settings = _eval_settings()
    instruction = str(
        getattr(args, "reranker_instruct", "") or settings.reranker_instruct
    ).strip()
    if not instruction:
        raise ValueError("M4 reranker instruction cannot be blank.")
    return instruction


def _resolved_config(args: argparse.Namespace, suite: dict) -> dict[str, Any]:
    _apply_embedding_profile(args)
    repository = Path(__file__).resolve().parents[3]
    m4_context = bool(
        getattr(args, "m4_capture", False)
        or int(suite.get("schemaVersion") or 0) == 5
    )
    m3_context = bool(
        getattr(args, "m3_capture_arm", None)
        or int(suite.get("schemaVersion") or 0) in {4, 5}
        or m4_context
    )
    query_rewrite_config = (
        _resolved_query_rewrite_config(args, repository) if m3_context else None
    )
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
            "fusionPoolLimit": args.fusion_pool_limit,
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
    if query_rewrite_config is not None:
        resolved["queryRewrite"] = query_rewrite_config
        resolved["features"].update(
            {
                "queryRewriteEnabled": query_rewrite_config["enabled"],
                "queryRewritePromptVersion": (
                    query_rewrite_config["promptVersion"]
                    if query_rewrite_config["enabled"]
                    else None
                ),
                "queryRewritePromptFingerprint": query_rewrite_config[
                    "promptFingerprint"
                ],
                "queryRewriteConfigFingerprint": rewrite_config_fingerprint(
                    resolved
                ),
            }
        )
    if m4_context:
        reranker_config = _resolved_reranker_config(args, repository)
        resolved["reranker"] = reranker_config
        resolved["features"].update(
            {
                "rerankerProvider": reranker_config["provider"],
                "rerankerEnabled": reranker_config["enabled"],
                "rerankerModel": reranker_config["model"],
                "rerankerModelVersion": reranker_config["version"],
                "rerankerConfigFingerprint": reranker_config_fingerprint(resolved),
                "rerankerInputVersion": reranker_config["inputVersion"],
                "rerankerInputBuilderFingerprint": reranker_config[
                    "inputBuilderFingerprint"
                ],
            }
        )
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
    rewrite_enabled = bool((resolved_config.get("features") or {}).get("queryRewriteEnabled"))
    m3_configured = isinstance(resolved_config.get("queryRewrite"), dict)
    reranker_enabled = bool((resolved_config.get("features") or {}).get("rerankerEnabled"))
    m4_configured = isinstance(resolved_config.get("reranker"), dict)
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
        "rewrite": (
            {
                "available": True,
                "source": "candidate-discovery-metadata",
            }
            if rewrite_enabled
            else {
                "available": False,
                "reason": "disabled M3 control" if m3_configured else "disabled in M0 baseline",
            }
        ),
        "reranker": (
            {"available": True, "source": "candidate-discovery-metadata"}
            if reranker_enabled
            else {
                "available": False,
                "reason": (
                    "heuristic M4 control"
                    if m4_configured
                    else "no learned reranker in baseline"
                ),
            }
        ),
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
            "reranker",
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
        if rewrite_enabled:
            rewrite_samples = sum(
                (item.get("latencyMs") or {}).get("queryRewrite") is not None
                for item in results
            )
            availability["rewrite"]["samples"] = rewrite_samples
            if rewrite_samples == 0:
                availability["rewrite"] = {
                    "available": False,
                    "reason": "service did not expose the rewrite timer",
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
    if not args.candidate_limit <= args.fusion_pool_limit <= min(
        args.global_merchant_limit,
        100,
    ):
        raise ValueError(
            "--fusion-pool-limit must be between candidate limit and the lower of "
            "global merchant limit or 100."
        )
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
    rewrite_provider = str(args.query_rewrite_provider)
    if rewrite_provider not in {"disabled", "openai", "deepseek"}:
        raise ValueError(
            "M0 accepts query_rewrite_provider in the config snapshot but only supports "
            f"'disabled' outside the implemented M3 providers; received {rewrite_provider!r}."
        )
    if rewrite_provider != "disabled":
        if not expected_enabled or args.split != "dev":
            raise ValueError("M3 query rewrite requires Dev global-hybrid retrieval.")
        if not 1 <= args.query_rewrite_max_queries <= 3:
            raise ValueError("--query-rewrite-max-queries must be between 1 and 3.")
        if not 0 < args.query_rewrite_timeout_seconds <= 60:
            raise ValueError("--query-rewrite-timeout-seconds must be in (0, 60].")
        if not 1 <= args.query_rewrite_max_concurrency <= 8:
            raise ValueError("--query-rewrite-max-concurrency must be between 1 and 8.")
        if args.query_rewrite_cache_size < 0 or args.query_rewrite_cache_ttl_seconds < 0:
            raise ValueError("M3 query rewrite cache bounds cannot be negative.")
        if args.query_rewrite_max_input_characters < 1:
            raise ValueError("--query-rewrite-max-input-characters must be positive.")
        if not 64 <= args.query_rewrite_max_output_tokens <= 2_000:
            raise ValueError("--query-rewrite-max-output-tokens must be between 64 and 2000.")
        for name in (
            "query_rewrite_input_price_usd_per_million_tokens",
            "query_rewrite_output_price_usd_per_million_tokens",
        ):
            value = getattr(args, name)
            if value is None or not math.isfinite(value) or value <= 0:
                raise ValueError(
                    "Enabled M3 rewrite requires explicit positive input/output token prices."
                )
        cap = args.query_rewrite_max_provider_cost_usd
        if not math.isfinite(cap) or not 0 < cap <= 0.1:
            raise ValueError("M3 rewrite provider cost cap must be in (0, 0.10] USD.")
        if not args.query_rewrite_prompt_version.strip():
            raise ValueError("M3 rewrite prompt version cannot be blank.")
    if args.reranker_provider not in {"heuristic-multi-signal", "qwen"}:
        raise ValueError(
            "M4 reranker provider must be 'heuristic-multi-signal' or 'qwen'."
        )
    if getattr(args, "m4_capture", False) and args.reranker_provider != "heuristic-multi-signal":
        raise ValueError("M4 pre-rerank capture must use the provider-free heuristic control.")
    if args.reranker_provider == "qwen":
        if not expected_enabled or args.split != "dev":
            raise ValueError("M4 learned reranking requires Dev global-hybrid retrieval.")
        if args.query_rewrite_provider == "disabled":
            raise ValueError("M4 learned reranking requires the accepted M3 query rewrite.")
        if args.reranker_model != "qwen3-rerank":
            raise ValueError("M4 qwen treatment is frozen to --reranker-model qwen3-rerank.")
        if args.reranker_candidate_limit != 30 or args.fusion_pool_limit != 30:
            raise ValueError("M4 requires a frozen Top-30 reranker and fusion pool.")
        if args.reranker_max_retries != 0:
            raise ValueError("Formal M4 forbids reranker retries.")
        cap = args.reranker_max_provider_cost_usd
        if not math.isfinite(cap) or not 0 < cap <= 0.5:
            raise ValueError("M4 reranker provider cost cap must be in (0, 0.50] USD.")
    if not 1 <= args.reranker_candidate_limit <= args.fusion_pool_limit:
        raise ValueError("--reranker-candidate-limit must fit within the fusion pool.")


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


def _validate_m3_run_configuration(
    args: argparse.Namespace,
    *,
    suite: dict[str, Any],
    resolved_config: dict[str, Any],
    repository: Path,
    scoped_source: dict[str, Any],
    runtime_environment: dict[str, str],
) -> bool:
    schema_version = int(suite.get("schemaVersion") or 0)
    capture_arm = getattr(args, "m3_capture_arm", None)
    if capture_arm is None and schema_version != 4:
        if args.query_rewrite_provider != "disabled":
            raise ValueError("Query rewrite may run only in an explicit M3 capture or schema-v4 Eval.")
        return False
    if suite.get("split") != "dev" or args.split != "dev":
        raise ValueError("M3 is Dev-only and permanently forbids the consumed M1 Test holdout.")
    if _file_sha256(args.quality_gate) != _file_sha256(M3_QUALITY_GATE_PATH):
        raise ValueError("M3 capture and formal Eval must use committed m3_quality_gate.json.")
    if _index_action(args) != "reuse":
        raise ValueError("M3 capture and formal Eval must reuse the exact frozen M1 index.")
    if args.global_retrieval_mode != "global-hybrid" or not args.global_retrieval_enabled:
        raise ValueError("M3 requires explicitly enabled global-hybrid retrieval in both arms.")
    if args.output is None:
        raise ValueError("M3 capture and formal Eval require an explicit --output path.")
    if args.limit_cases is not None:
        raise ValueError("M3 capture and formal Eval must run all frozen Dev cases.")
    if args.baseline_report is not None or args.candidate_universe_output is not None:
        raise ValueError("M3 uses paired reports; baseline and M2 candidate output flags are forbidden.")
    protected = [path for path in (args.output, args.summary_output) if path is not None]
    if len({path.resolve() for path in protected}) != len(protected):
        raise ValueError("M3 report and summary paths must be distinct.")
    for path in protected:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite frozen M3 output: {path}")
    if scoped_source.get("dirty") is not False:
        raise ValueError("M3 requires a clean scoped Eval/retrieval/rewrite source snapshot.")
    git = _git_snapshot(repository)
    if git.get("dirty") is not False or not git.get("sha"):
        raise ValueError("M3 requires a clean Git source identity.")

    config_fingerprint = _fingerprint(resolved_config)
    experiment_fingerprint = m3_experiment_fingerprint(resolved_config)
    rewrite_fingerprint = rewrite_config_fingerprint(resolved_config)
    rewrite = resolved_config["queryRewrite"]
    treatment = args.query_rewrite_provider != "disabled"
    if capture_arm is not None:
        if schema_version != 3:
            raise ValueError("--m3-capture-arm requires the frozen schema-v3 M2 Dev suite.")
        expected_treatment = capture_arm == "treatment"
        if treatment is not expected_treatment:
            raise ValueError(
                "M3 control capture must disable rewrite and treatment capture must enable it."
            )
        return True

    contract = suite["judgmentContract"]
    expected_arm = "treatment" if treatment else "control"
    expected_config = contract[f"{expected_arm}ConfigFingerprint"]
    expected_rewrite = contract[f"{expected_arm}RewriteConfigFingerprint"]
    if config_fingerprint != expected_config or rewrite_fingerprint != expected_rewrite:
        raise ValueError("M3 formal runtime differs from its captured arm configuration.")
    if experiment_fingerprint != contract["experimentFingerprint"]:
        raise ValueError("M3 formal runtime differs outside the isolated rewrite configuration.")
    if int(contract["candidateLimit"]) != args.candidate_limit:
        raise ValueError("M3 candidate limit differs from its bounded judgment contract.")
    if scoped_source["sha256"] != contract["captureScopedSourceSha256"]:
        raise ValueError("M3 scoped source changed after candidate capture.")
    if runtime_environment != contract["captureRuntimeEnvironment"]:
        raise ValueError("M3 runtime environment changed after candidate capture.")
    if git["sha"] != contract["captureSourceGitSha"]:
        raise ValueError("M3 Git identity changed after candidate capture.")
    if treatment and (
        rewrite["promptVersion"] != contract["treatmentPromptVersion"]
        or rewrite["promptFingerprint"] != contract["treatmentPromptFingerprint"]
    ):
        raise ValueError("M3 treatment prompt changed after candidate capture.")
    return False


def _validate_m4_run_configuration(
    args: argparse.Namespace,
    *,
    suite: dict[str, Any],
    resolved_config: dict[str, Any],
    repository: Path,
    scoped_source: dict[str, Any],
    runtime_environment: dict[str, str],
) -> bool:
    capture_only = bool(getattr(args, "m4_capture", False))
    schema_version = int(suite.get("schemaVersion") or 0)
    if capture_only:
        if schema_version != 4:
            raise ValueError("--m4-capture requires the frozen schema-v4 M3 Dev suite.")
        validate_frozen_m3_dev_source_suite(suite)
    elif schema_version != 5:
        raise ValueError("Formal M4 requires the frozen schema-v5 Dev suite.")
    if suite.get("split") != "dev" or args.split != "dev":
        raise ValueError("M4 is Dev-only and forbids the consumed M1 Test holdout.")
    if _file_sha256(args.quality_gate) != _file_sha256(M4_QUALITY_GATE_PATH):
        raise ValueError("M4 capture and formal Eval require committed m4_quality_gate.json.")
    if _index_action(args) != "reuse":
        raise ValueError("M4 must reuse the exact frozen M1 index.")
    if args.global_retrieval_mode != "global-hybrid" or not args.global_retrieval_enabled:
        raise ValueError("M4 requires global-hybrid retrieval.")
    if args.query_rewrite_provider == "disabled":
        raise ValueError("M4 requires the accepted M3 query-rewrite treatment.")
    if args.fusion_pool_limit != 30 or args.reranker_candidate_limit != 30:
        raise ValueError("M4 requires one frozen pre-rerank Top-30 pool.")
    if args.candidate_limit != 10:
        raise ValueError("M4 final candidate limit is frozen to Top-10.")
    if capture_only and args.reranker_provider != "heuristic-multi-signal":
        raise ValueError("M4 candidate capture must not call a learned reranker.")
    if args.output is None or args.limit_cases is not None:
        raise ValueError("M4 requires an output path and all frozen Dev cases.")
    if args.baseline_report is not None or args.candidate_universe_output is not None:
        raise ValueError("M4 uses paired reports; baseline/candidate-output flags are forbidden.")
    protected = [path for path in (args.output, args.summary_output) if path is not None]
    if len({path.resolve() for path in protected}) != len(protected):
        raise ValueError("M4 report and summary paths must be distinct.")
    for path in protected:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite frozen M4 output: {path}")
    if scoped_source.get("dirty") is not False:
        raise ValueError("M4 requires a clean scoped source snapshot.")
    git = _git_snapshot(repository)
    if git.get("dirty") is not False or not git.get("sha"):
        raise ValueError("M4 requires a clean Git source identity.")

    experiment = m4_experiment_fingerprint(resolved_config)
    rewrite_fingerprint = rewrite_config_fingerprint(resolved_config)
    rewrite = resolved_config["queryRewrite"]
    if capture_only:
        return True
    contract = suite["judgmentContract"]
    if experiment != contract["experimentFingerprint"]:
        raise ValueError("M4 runtime differs outside the isolated reranker configuration.")
    if rewrite_fingerprint != contract["rewriteConfigFingerprint"]:
        raise ValueError("M4 query rewrite differs from candidate capture.")
    if (
        rewrite["promptVersion"] != contract["rewritePromptVersion"]
        or rewrite["promptFingerprint"] != contract["rewritePromptFingerprint"]
    ):
        raise ValueError("M4 rewrite prompt differs from candidate capture.")
    if scoped_source["sha256"] != contract["captureScopedSourceSha256"]:
        raise ValueError("M4 scoped source changed after candidate capture.")
    if runtime_environment != contract["captureRuntimeEnvironment"]:
        raise ValueError("M4 runtime environment changed after candidate capture.")
    if git["sha"] != contract["captureSourceGitSha"]:
        raise ValueError("M4 Git identity changed after candidate capture.")
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
    source_dev_suite = (
        trusted_source_suite
        if trusted_source_suite is not None
        else json.loads((EVAL_DIRECTORY / "cases.dev.json").read_text(encoding="utf-8"))
    )
    source_by_case = {str(case["id"]): case for case in source_dev_suite["cases"]}
    for case in suite["cases"]:
        metadata = case.get("metadata") or {}
        if "structuredCandidateExternalIds" not in metadata:
            raise ValueError(
                f"M2 case {case['id']} is missing its captured structured branch."
            )
        if not isinstance(metadata["structuredCandidateExternalIds"], list):
            raise ValueError(
                f"M2 case {case['id']} structured branch external IDs must be a list."
            )
        if not isinstance(metadata.get("treatmentReturnedExternalIds"), list):
            raise ValueError(
                f"M2 case {case['id']} treatment external IDs must be a list."
            )
        structured = list(metadata["structuredCandidateExternalIds"])
        treatment = list(metadata["treatmentReturnedExternalIds"])
        universe_case = universe_by_case[str(case["id"])]
        if not isinstance(universe_case.get("structuredBranchExternalIds"), list):
            raise ValueError(
                f"M2 candidate universe {case['id']} is missing its captured structured branch."
            )
        fixture_structured = list(universe_case["structuredBranchExternalIds"])
        fixture_treatment = list(universe_case["returnedExternalIds"])
        if structured != fixture_structured:
            raise ValueError(
                f"M2 case {case['id']} differs from its captured structured branch."
            )
        if treatment != fixture_treatment:
            raise ValueError(f"M2 case {case['id']} differs from its captured treatment output.")
        if (
            any(not isinstance(item, str) or not item for item in structured)
            or len(structured) != len(set(structured))
            or any(not isinstance(item, str) or not item for item in treatment)
            or len(treatment) != len(set(treatment))
        ):
            raise ValueError(f"M2 case {case['id']} has duplicate candidate-universe IDs.")
        source_judgment_ids = {
            str(item["externalId"])
            for item in source_by_case[str(case["id"])]["judgments"]
        }
        if not set(structured) <= source_judgment_ids:
            raise ValueError(
                f"M2 case {case['id']} structured branch is outside the committed "
                "M1 Dev judgments."
            )
        judged = {str(item["externalId"]): item for item in case["judgments"]}
        expected_qdrant_only = sorted(set(treatment) - set(structured))
        if not set(structured) | set(treatment) <= judged.keys():
            raise ValueError(f"M2 case {case['id']} does not label its bounded candidate union.")
        expected_metadata_counts = {
            "structuredCandidateCount": len(structured),
            "treatmentReturnedCount": len(treatment),
            "qdrantOnlyJudgmentCount": len(expected_qdrant_only),
            "boundedJudgmentCount": len(judged),
        }
        for field, expected in expected_metadata_counts.items():
            if metadata.get(field) != expected:
                raise ValueError(
                    f"M2 case {case['id']} has an invalid {field}."
                )
        if metadata.get("qdrantOnlyJudgmentExternalIds") != expected_qdrant_only:
            raise ValueError(f"M2 case {case['id']} has inconsistent Qdrant-only judgments.")
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
    if int(fixture.get("structuredCandidatePairCount", -1)) != structured_pairs:
        raise ValueError(
            "M2 candidate-universe structuredCandidatePairCount is inconsistent."
        )
    for field, expected in expected_counts.items():
        if int(contract.get(field) or 0) != expected:
            raise ValueError(f"M2 judgment contract {field} is inconsistent.")
    if qdrant_only_pairs < 1 or relevant_miss_pairs < 1:
        raise ValueError("M2 suite does not exercise a relevant structured-miss rescue.")
    if int(contract.get("fullCartesianPairsAvoided") or 0) <= 0:
        raise ValueError("M2 suite must document avoidance of the full corpus Cartesian product.")


def _validate_m3_judgment_contract(directory: Path, suite: dict[str, Any]) -> None:
    if suite.get("suite") != M3_SUITE_NAME or suite.get("split") != "dev":
        raise ValueError("Schema-v4 M3 evaluation is Dev-only and uses the dedicated M3 suite.")
    contract = suite.get("judgmentContract") or {}
    if (
        contract.get("policyVersion") != M3_JUDGMENT_POLICY_VERSION
        or contract.get("unjudgedReturnedPolicy") != "fail-closed"
        or contract.get("sourceSplit") != "dev"
        or contract.get("m1PolicyHoldoutUsed") is not False
        or contract.get("m1PolicyHoldoutForbidden") is not True
        or contract.get("selectionLeakageWarning") != M3_SELECTION_LEAKAGE_WARNING
    ):
        raise ValueError("M3 suite violates its Dev-only fail-closed judgment policy.")
    if (suite.get("evaluationDesign") or {}).get("m1PolicyHoldoutUsed") is not False:
        raise ValueError("M3 suite may not use the consumed M1 Test holdout.")

    source_suite = json.loads(FROZEN_M2_DEV_SUITE_PATH.read_text(encoding="utf-8"))
    validate_frozen_m2_dev_source_suite(
        source_suite,
        trusted_source_suite=source_suite,
    )
    source_identity = {
        "sourceSuite": source_suite["suite"],
        "sourceSuiteSchemaVersion": 3,
        "sourceSuiteCaseSha256": source_suite["caseSha256"],
        "sourceSuiteContractSha256": source_suite["suiteContractSha256"],
        "sourceJudgmentContractSha256": sha256_json(source_suite["judgmentContract"]),
    }
    if any(contract.get(field) != value for field, value in source_identity.items()):
        raise ValueError("M3 judgment contract is not derived from frozen M2 Dev.")

    fixture_name = contract.get("candidateUniverseFixture")
    if (
        fixture_name != M3_CANDIDATE_UNIVERSE_FILENAME
        or Path(str(fixture_name)).name != fixture_name
    ):
        raise ValueError("M3 suite references an invalid candidate-universe fixture.")
    fixture_path = directory / fixture_name
    if not fixture_path.is_file():
        raise ValueError(f"M3 suite requires its sibling {fixture_name} fixture.")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_sha = m3_candidate_universe_sha256(fixture)
    if (
        fixture.get("fixtureSha256") != fixture_sha
        or contract.get("candidateUniverseFixtureSha256") != fixture_sha
    ):
        raise ValueError("M3 candidate-universe fixture SHA does not match the suite contract.")
    expected_fixture = {
        "split": "dev",
        **source_identity,
        "dataVersion": suite["dataVersion"],
        "datasetSha256": suite["datasetSha256"],
        "candidateLimit": contract.get("candidateLimit"),
        "experimentFingerprint": contract.get("experimentFingerprint"),
        "controlConfigFingerprint": contract.get("controlConfigFingerprint"),
        "treatmentConfigFingerprint": contract.get("treatmentConfigFingerprint"),
        "controlResultFingerprint": contract.get("controlResultFingerprint"),
        "treatmentResultFingerprint": contract.get("treatmentResultFingerprint"),
        "indexManifestFingerprint": contract.get("captureIndexManifestFingerprint"),
        "scopedSourceSha256": contract.get("captureScopedSourceSha256"),
        "sourceGitSha": contract.get("captureSourceGitSha"),
        "runtimeEnvironment": contract.get("captureRuntimeEnvironment"),
        "runtimeEnvironmentFingerprint": contract.get(
            "captureRuntimeEnvironmentFingerprint"
        ),
        "qdrantServer": contract.get("captureQdrantServer"),
        "qdrantServerFingerprint": contract.get("captureQdrantServerFingerprint"),
        "embeddingIdentity": contract.get("embeddingIdentity"),
        "controlRewriteConfigFingerprint": contract.get(
            "controlRewriteConfigFingerprint"
        ),
        "treatmentRewriteConfigFingerprint": contract.get(
            "treatmentRewriteConfigFingerprint"
        ),
        "treatmentPromptVersion": contract.get("treatmentPromptVersion"),
        "treatmentPromptFingerprint": contract.get("treatmentPromptFingerprint"),
        "selectionLeakageWarning": M3_SELECTION_LEAKAGE_WARNING,
        "caseCount": int(suite["caseCount"]),
    }
    if any(fixture.get(field) != value for field, value in expected_fixture.items()):
        raise ValueError("M3 candidate-universe fixture differs from its judgment contract.")

    universe_cases = fixture.get("cases")
    expected_ids = [str(case["id"]) for case in suite["cases"]]
    if not isinstance(universe_cases, list) or [
        str(case.get("id")) for case in universe_cases
    ] != expected_ids:
        raise ValueError("M3 candidate-universe case order/IDs differ from the suite.")
    universe_by_id = {str(case["id"]): case for case in universe_cases}
    counts = {"structured": 0, "control": 0, "treatment": 0, "bounded": 0}
    treatment_only = 0
    relevant_treatment_only = 0
    threshold = int(suite["binaryRelevanceThreshold"])
    for case in suite["cases"]:
        case_id = str(case["id"])
        universe = universe_by_id[case_id]

        def external_ids(
            field: str,
            *,
            current_universe: dict[str, Any] = universe,
            current_case_id: str = case_id,
        ) -> list[str]:
            value = current_universe.get(field)
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item for item in value)
                or len(value) != len(set(value))
            ):
                raise ValueError(
                    f"M3 candidate universe {current_case_id} has invalid {field}."
                )
            return value

        structured = external_ids("structuredBranchExternalIds")
        control = external_ids("m2ControlReturnedExternalIds")
        treatment = external_ids("m3TreatmentReturnedExternalIds")
        if len(control) > int(contract["candidateLimit"]) or len(treatment) > int(
            contract["candidateLimit"]
        ):
            raise ValueError(f"M3 candidate universe {case_id} exceeds its Top-K bound.")
        judged = {str(item["externalId"]): item for item in case.get("judgments") or []}
        bounded_ids = set(structured) | set(control) | set(treatment)
        if set(judged) != bounded_ids:
            raise ValueError(f"M3 case {case_id} is not complete for its bounded union.")
        metadata = case.get("metadata") or {}
        expected_metadata = {
            "structuredCandidateExternalIds": structured,
            "m2ControlReturnedExternalIds": control,
            "m3TreatmentReturnedExternalIds": treatment,
            "boundedJudgmentCount": len(judged),
        }
        if any(metadata.get(field) != value for field, value in expected_metadata.items()):
            raise ValueError(f"M3 case {case_id} metadata differs from candidate capture.")
        new_ids = set(treatment) - set(structured) - set(control)
        treatment_only += len(new_ids)
        relevant_treatment_only += sum(
            int(judged[external_id]["relevance"]) >= threshold for external_id in new_ids
        )
        counts["structured"] += len(structured)
        counts["control"] += len(control)
        counts["treatment"] += len(treatment)
        counts["bounded"] += len(judged)

    expected_counts = {
        "structuredJudgmentPairs": counts["structured"],
        "m2ControlObservedPairs": counts["control"],
        "m3TreatmentObservedPairs": counts["treatment"],
        "boundedJudgmentPairs": counts["bounded"],
        "m3TreatmentOnlyJudgmentPairs": treatment_only,
        "binaryRelevantM3TreatmentOnlyPairs": relevant_treatment_only,
    }
    for field, expected in expected_counts.items():
        value = contract.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise ValueError(f"M3 judgment contract {field} is inconsistent.")
    if treatment_only < 1 or relevant_treatment_only < 1:
        raise ValueError("M3 suite does not exercise a relevant treatment-only rescue.")


def _validate_m4_judgment_contract(directory: Path, suite: dict[str, Any]) -> None:
    if suite.get("suite") != M4_SUITE_NAME or suite.get("split") != "dev":
        raise ValueError("Schema-v5 Eval accepts only the frozen M4 Dev suite.")
    contract = suite.get("judgmentContract")
    if (
        not isinstance(contract, dict)
        or contract.get("policyVersion") != M4_JUDGMENT_POLICY_VERSION
        or contract.get("unjudgedReturnedPolicy") != "fail-closed"
        or contract.get("sourceSplit") != "dev"
        or contract.get("m1PolicyHoldoutUsed") is not False
        or contract.get("m1PolicyHoldoutForbidden") is not True
        or contract.get("selectionLeakageWarning") != M4_SELECTION_LEAKAGE_WARNING
        or int(contract.get("candidateLimit") or 0) != 30
        or int(contract.get("finalCandidateLimit") or 0) != 10
    ):
        raise ValueError("M4 suite has an invalid complete-pool judgment contract.")
    fixture_name = contract.get("candidateUniverseFixture")
    if (
        fixture_name != M4_CANDIDATE_UNIVERSE_FILENAME
        or Path(str(fixture_name)).name != fixture_name
    ):
        raise ValueError("M4 suite references an invalid candidate-universe fixture.")
    fixture_path = directory / fixture_name
    if not fixture_path.is_file():
        raise ValueError(f"M4 suite requires its sibling {fixture_name} fixture.")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_sha = m4_candidate_universe_sha256(fixture)
    if (
        fixture.get("fixtureSha256") != fixture_sha
        or contract.get("candidateUniverseFixtureSha256") != fixture_sha
        or contract.get("candidatePoolContractSha256")
        != fixture.get("candidatePoolContractSha256")
    ):
        raise ValueError("M4 candidate-universe fixture differs from its suite contract.")
    fixture_cases = fixture.get("cases")
    if not isinstance(fixture_cases, list) or [str(row.get("id")) for row in fixture_cases] != [
        str(row.get("id")) for row in suite.get("cases") or []
    ]:
        raise ValueError("M4 candidate-universe case order/IDs differ from the suite.")
    fixture_by_id = {str(row["id"]): row for row in fixture_cases}
    pair_count = 0
    for case in suite["cases"]:
        case_id = str(case["id"])
        frozen = fixture_by_id[case_id]
        pool_ids = frozen.get("preRerankCandidateExternalIds")
        if (
            not isinstance(pool_ids, list)
            or not pool_ids
            or len(pool_ids) > 30
            or len(pool_ids) != len(set(pool_ids))
            or frozen.get("preRerankPoolFingerprint") != sha256_json(pool_ids)
        ):
            raise ValueError(f"M4 case {case_id} has an invalid frozen Top-30 pool.")
        judged_ids = {str(item["externalId"]) for item in case.get("judgments") or []}
        if judged_ids != set(pool_ids):
            raise ValueError(f"M4 case {case_id} is not fully judged for its frozen pool.")
        metadata = case.get("metadata") or {}
        expected_metadata = {
            "preRerankCandidateExternalIds": pool_ids,
            "preRerankPoolFingerprint": frozen["preRerankPoolFingerprint"],
            "rerankerInputFingerprint": frozen["rerankerInputFingerprint"],
            "boundedJudgmentCount": len(pool_ids),
        }
        if any(metadata.get(field) != value for field, value in expected_metadata.items()):
            raise ValueError(f"M4 case {case_id} metadata differs from candidate capture.")
        pair_count += len(pool_ids)
    if pair_count != contract.get("preRerankCandidatePairs"):
        raise ValueError("M4 complete-pool judgment count is inconsistent.")


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


def _m3_scoped_source_snapshot(repository: Path) -> dict[str, Any]:
    snapshot = _file_set_fingerprint(repository, M3_EVAL_SOURCE_PATHS)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *M3_EVAL_SOURCE_PATHS],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {
        **snapshot,
        "dirty": bool(status),
    }


def _m4_scoped_source_snapshot(repository: Path) -> dict[str, Any]:
    snapshot = _file_set_fingerprint(repository, M4_EVAL_SOURCE_PATHS)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *M4_EVAL_SOURCE_PATHS],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {**snapshot, "dirty": bool(status)}


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
    source_git: dict[str, Any],
    runtime_environment: dict[str, str],
    index_report: dict[str, Any],
    candidate_universe: dict[str, Any] | None,
) -> dict[str, Any]:
    judgment_contract = suite.get("judgmentContract")
    m4_run = int(suite.get("schemaVersion") or 0) == 5 or isinstance(
        resolved_config.get("reranker"), dict
    )
    m3_run = not m4_run and (int(suite.get("schemaVersion") or 0) == 4 or isinstance(
        resolved_config.get("queryRewrite"),
        dict,
    ))
    manifest = {
        "version": (
            "rag-v2-eval-manifest-v4"
            if m4_run
            else "rag-v2-eval-manifest-v3"
            if m3_run
            else "rag-v2-eval-manifest-v2"
        ),
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
        "scopedSourceSha256": scoped_source.get("sha256"),
        "runtimeEnvironmentFingerprint": _fingerprint(runtime_environment),
        "indexManifestFingerprint": index_report.get("manifestFingerprint"),
        "qdrantServerFingerprint": _fingerprint(index_report.get("qdrantServer") or {}),
        "embeddingIdentity": (resolved_config.get("embedding") or {}).get("identity"),
        "retrievalMode": (resolved_config.get("retrieval") or {}).get("mode"),
        "globalRetrievalEnabled": (resolved_config.get("features") or {}).get("globalRetrievalEnabled"),
    }
    if m4_run:
        features = resolved_config.get("features") or {}
        rewrite = resolved_config["queryRewrite"]
        contract = judgment_contract or {}
        manifest.update(
            {
                "m4ExperimentFingerprint": experiment_fingerprint,
                "sourceGitSha": source_git.get("sha"),
                "queryRewriteProvider": features.get("queryRewriteProvider"),
                "queryRewriteEnabled": features.get("queryRewriteEnabled"),
                "promptFingerprint": rewrite.get("promptFingerprint"),
                "rewriteConfigFingerprint": rewrite_config_fingerprint(resolved_config),
                "rerankerProvider": features.get("rerankerProvider"),
                "rerankerEnabled": features.get("rerankerEnabled"),
                "rerankerConfigFingerprint": reranker_config_fingerprint(
                    resolved_config
                ),
                "candidatePoolContractSha256": contract.get(
                    "candidatePoolContractSha256"
                ),
            }
        )
    elif m3_run:
        features = resolved_config.get("features") or {}
        rewrite = resolved_config["queryRewrite"]
        manifest.update(
            {
                "m3ExperimentFingerprint": experiment_fingerprint,
                "sourceGitSha": source_git.get("sha"),
                "queryRewriteProvider": features.get("queryRewriteProvider"),
                "queryRewriteEnabled": features.get("queryRewriteEnabled"),
                "promptFingerprint": rewrite.get("promptFingerprint"),
                "rewriteConfigFingerprint": rewrite_config_fingerprint(
                    resolved_config
                ),
            }
        )
    else:
        manifest["m2ExperimentFingerprint"] = experiment_fingerprint
    return manifest


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


def _rewrite_cost_from_results(results: list[dict[str, Any]]) -> float:
    cost = 0.0
    for result in results:
        value = (
            ((result.get("requests") or {}).get("rewriteProviderUsage") or {}).get(
                "estimated_cost_usd",
                0.0,
            )
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("M3 rewrite cost must be numeric.")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("M3 rewrite cost must be finite and non-negative.")
        cost += value
    return cost


def _reranker_cost_from_results(results: list[dict[str, Any]]) -> float:
    cost = 0.0
    for result in results:
        value = (
            ((result.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                "estimated_cost_usd", 0.0
            )
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("M4 reranker cost must be numeric.")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("M4 reranker cost must be finite and non-negative.")
        cost += value
    return cost


def _summarize_m4_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_results(results)
    request_counts = summary["requestCounts"]
    request_counts.update(
        {
            "rerankerProviderNetworkRequests": sum(
                int(
                    ((row.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                        "network_requests", 0
                    )
                )
                for row in results
            ),
            "rerankerProviderTokens": sum(
                int(
                    ((row.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                        "total_tokens", 0
                    )
                )
                for row in results
            ),
            "rerankerProviderRetries": sum(
                int(
                    ((row.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                        "retry_count", 0
                    )
                )
                for row in results
            ),
            "rerankerProviderFailures": sum(
                int(
                    ((row.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                        "failure_count", 0
                    )
                )
                for row in results
            ),
            "rerankerCacheHits": sum(
                int(
                    ((row.get("requests") or {}).get("rerankerProviderUsage") or {}).get(
                        "cache_hits", 0
                    )
                )
                for row in results
            ),
            "rerankerFallbacks": sum(
                bool((row.get("requests") or {}).get("rerankerFallback", False))
                for row in results
            ),
        }
    )
    summary.setdefault("costUsd", {})["reranker"] = _reranker_cost_from_results(
        results
    )
    return summary


def _require_rewrite_cost_within_cap(
    estimated_cost_usd: float,
    resolved_config: dict[str, Any],
) -> None:
    cap = float((resolved_config.get("queryRewrite") or {}).get("maxProviderCostUsd", 0.0))
    if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
        raise ValueError("M3 rewrite provider produced an invalid cost estimate.")
    if estimated_cost_usd > cap + 1e-9:
        raise ValueError(
            f"M3 rewrite provider cost ${estimated_cost_usd:.6f} exceeded hard cap ${cap:.6f}."
        )


def _require_reranker_cost_within_cap(
    estimated_cost_usd: float,
    resolved_config: dict[str, Any],
) -> None:
    cap = float((resolved_config.get("reranker") or {}).get("maxProviderCostUsd", 0.0))
    if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
        raise ValueError("M4 reranker produced an invalid cost estimate.")
    if estimated_cost_usd > cap + 1e-9:
        raise ValueError(
            f"M4 reranker cost ${estimated_cost_usd:.6f} exceeded hard cap ${cap:.6f}."
        )


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
    parser.add_argument(
        "--query-rewrite-provider",
        choices=("disabled", "openai", "deepseek"),
        default="disabled",
    )
    parser.add_argument("--query-rewrite-base-url", default="")
    parser.add_argument("--query-rewrite-model", default="")
    parser.add_argument("--query-rewrite-prompt-version", default=PROMPT_VERSION)
    parser.add_argument("--query-rewrite-max-queries", type=int, default=3)
    parser.add_argument("--query-rewrite-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--query-rewrite-max-concurrency", type=int, default=2)
    parser.add_argument("--query-rewrite-cache-size", type=int, default=512)
    parser.add_argument("--query-rewrite-cache-ttl-seconds", type=float, default=900.0)
    parser.add_argument("--query-rewrite-max-input-characters", type=int, default=2_000)
    parser.add_argument("--query-rewrite-max-output-tokens", type=int, default=300)
    parser.add_argument(
        "--query-rewrite-input-price-usd-per-million-tokens",
        type=float,
    )
    parser.add_argument(
        "--query-rewrite-output-price-usd-per-million-tokens",
        type=float,
    )
    parser.add_argument("--query-rewrite-max-provider-cost-usd", type=float, default=0.1)
    parser.add_argument(
        "--m3-capture-arm",
        choices=("control", "treatment"),
        help="Run a complete, non-scoring schema-v3 M3 candidate capture arm.",
    )
    parser.add_argument(
        "--m4-capture",
        action="store_true",
        help="Capture one provider-free M3 pre-rerank Top-30 pool for both M4 arms.",
    )
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
    parser.add_argument("--fusion-pool-limit", type=int, default=30)
    parser.add_argument("--global-documents-per-merchant", type=int, default=3)
    parser.add_argument("--global-hydration-concurrency", type=int, default=8)
    parser.add_argument("--global-branch-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--fusion-rrf-k", type=int, default=60)
    parser.add_argument("--brand-cap", type=int, default=2)
    parser.add_argument(
        "--reranker-provider",
        choices=("heuristic-multi-signal", "qwen"),
        default="heuristic-multi-signal",
    )
    parser.add_argument("--reranker-base-url", default="")
    parser.add_argument("--reranker-model", default="qwen3-rerank")
    parser.add_argument("--reranker-version", default="")
    parser.add_argument("--reranker-instruct", default="")
    parser.add_argument(
        "--reranker-instruction-version",
        default="m4-reranker-instruction-v1",
    )
    parser.add_argument("--reranker-input-version", default="merchant-rerank-text-v1")
    parser.add_argument("--reranker-candidate-limit", type=int, default=30)
    parser.add_argument("--reranker-max-document-characters", type=int, default=1_600)
    parser.add_argument("--reranker-max-evidence-excerpts", type=int, default=2)
    parser.add_argument("--reranker-max-evidence-characters", type=int, default=500)
    parser.add_argument("--reranker-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--reranker-max-concurrency", type=int, default=2)
    parser.add_argument("--reranker-max-retries", type=int, default=0)
    parser.add_argument("--reranker-cache-size", type=int, default=512)
    parser.add_argument("--reranker-cache-ttl-seconds", type=float, default=900.0)
    parser.add_argument("--reranker-circuit-failure-threshold", type=int, default=3)
    parser.add_argument("--reranker-circuit-cooldown-seconds", type=float, default=30.0)
    parser.add_argument(
        "--reranker-input-price-usd-per-million-tokens",
        type=float,
        default=0.11,
    )
    parser.add_argument("--reranker-max-provider-cost-usd", type=float, default=0.5)
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
