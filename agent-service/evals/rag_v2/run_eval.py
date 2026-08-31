from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.config import Settings
from app.domain.models import UserConstraints
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingService,
    OpenAICompatibleEmbeddingService,
)
from app.rag.nyc_loader import iter_generated_documents
from app.rag.qdrant_store import QdrantRagService
from app.runtime import _validate_data_directory
from app.tools.services import GeneratedNycShopToolService
from evals.rag_v2.contract import fixture_contract_sha256, suite_contract_sha256
from evals.rag_v2.metrics import (
    hard_constraint_violations,
    integrity_metrics,
    ranking_metrics,
    rounded,
    summarize_results,
)

EVAL_DIRECTORY = Path(__file__).resolve().parent
INDEX_BUILD_VERSION = "rag-document-transform-v2"
INDEX_BUILD_SOURCE_PATHS = (
    "agent-service/app/rag/embeddings.py",
    "agent-service/app/rag/lexical.py",
    "agent-service/app/rag/models.py",
    "agent-service/app/rag/nyc_loader.py",
    "agent-service/app/rag/qdrant_store.py",
)
EVAL_SOURCE_PATHS = (
    "agent-service/app/domain/models.py",
    "agent-service/app/rag/display_text.py",
    *INDEX_BUILD_SOURCE_PATHS,
    "agent-service/app/rag/query_plan.py",
    "agent-service/app/tools/services.py",
    "agent-service/evals/rag_v2/build_cases.py",
    "agent-service/evals/rag_v2/contract.py",
    "agent-service/evals/rag_v2/metrics.py",
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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            return await self._inner.embed(texts)
        finally:
            self.requests += 1
            self.texts += len(texts)
            self.latency_ms += (time.perf_counter() - started) * 1_000

    def reset(self) -> None:
        self.requests = 0
        self.texts = 0
        self.latency_ms = 0.0

    def snapshot(self) -> dict[str, float | int]:
        return {
            "embeddingRequests": self.requests,
            "embeddedTexts": self.texts,
            "embeddingLatencyMs": self.latency_ms,
        }


def load_suite(path: Path, data_directory: Path, *, expected_split: str | None = None) -> tuple[dict, dict]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    validated_data_version, validated_dataset_sha, _ = _validate_data_directory(data_directory)
    manifest = json.loads(
        (data_directory / "import_manifest.json").read_text(encoding="utf-8")
    )
    if int(suite.get("schemaVersion") or 0) != 2:
        raise ValueError("RAG v2 suite must use schemaVersion=2.")
    if expected_split and suite.get("split") != expected_split:
        raise ValueError(
            f"Eval suite split={suite.get('split')!r} does not match requested {expected_split!r}."
        )
    for field in ("dataVersion", "datasetSha256"):
        if suite.get(field) != manifest.get(field):
            raise ValueError(
                f"Eval suite {field}={suite.get(field)!r} does not match corpus "
                f"{manifest.get(field)!r}. Regenerate the suite for this exact corpus."
            )
    if suite.get("dataVersion") != validated_data_version:
        raise ValueError("Eval suite dataVersion does not match the validated corpus files.")
    if suite.get("datasetSha256") != validated_dataset_sha:
        raise ValueError("Eval suite datasetSha256 does not match the validated corpus files.")
    cases = suite.get("cases") or []
    if int(suite.get("caseCount") or 0) != len(cases):
        raise ValueError("Eval suite caseCount does not match its case list.")
    canonical = _canonical_json(cases)
    actual_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if suite.get("caseSha256") != actual_sha:
        raise ValueError("Eval suite caseSha256 does not match its canonical case list.")
    actual_contract_sha = suite_contract_sha256(suite)
    if suite.get("suiteContractSha256") != actual_contract_sha:
        raise ValueError(
            "Eval suite suiteContractSha256 does not match its frozen evaluation contract."
        )
    _validate_adversarial_fixture(path.parent, suite)
    _validate_cases(suite)
    return suite, manifest


async def evaluate_case(runtime: Any, case: dict, suite: dict, *, candidate_limit: int) -> dict:
    constraints = UserConstraints.model_validate(case["constraints"])
    runtime.embedding_service.reset()
    total_started = time.perf_counter()

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

    started = time.perf_counter()
    evidence = await runtime.rag_service.retrieve(constraints, ranked)
    evidence_ms = (time.perf_counter() - started) * 1_000
    total_ms = (time.perf_counter() - total_started) * 1_000
    embedding = runtime.embedding_service.snapshot()

    external_ids = [candidate.external_id for candidate in ranked.candidates]
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
    judgments = {str(item["externalId"]): item for item in case["judgments"]}
    ordered = []
    for position, candidate in enumerate(ranked.candidates, start=1):
        judgment = judgments.get(str(candidate.external_id))
        dynamic_violations, dynamic_unknowns = hard_constraint_violations(
            candidate, case["hardConstraints"]
        )
        ordered.append(
            {
                "rank": position,
                "shopId": candidate.shop_id,
                "externalId": candidate.external_id,
                "name": candidate.name,
                "relevance": int(judgment["relevance"]) if judgment else 0,
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
        "candidatePoolSize": len(candidate_pool.candidates),
        "returnedCount": len(ranked.candidates),
        "relevantJudgmentCount": sum(
            int(item["relevance"]) >= int(suite["binaryRelevanceThreshold"])
            for item in case["judgments"]
        ),
        "metrics": metrics,
        "integrity": integrity,
        "constraintFailures": violations,
        "latencyMs": {
            "structuredSearch": structured_ms,
            "candidateRanking": ranking_ms,
            "evidenceRetrieval": evidence_ms,
            "embedding": embedding["embeddingLatencyMs"],
            "total": total_ms,
        },
        "requests": {
            "embeddingRequests": embedding["embeddingRequests"],
            "embeddedTexts": embedding["embeddedTexts"],
            "rewriteRequests": 0,
            "rerankerRequests": 0,
            "providerUsage": None,
        },
        "orderedCandidates": ordered,
        "retrievalMetadata": {
            "candidatePool": candidate_pool.retrieval_metadata,
            "ranking": ranked.retrieval_metadata,
            "evidence": evidence.retrieval_metadata,
        },
    }


async def run(args: argparse.Namespace) -> tuple[dict, bool]:
    _validate_feature_configuration(args)
    repository = Path(__file__).resolve().parents[3]
    data_directory = args.data_directory.resolve()
    cases_path = args.cases or EVAL_DIRECTORY / f"cases.{args.split}.json"
    suite, manifest = load_suite(cases_path.resolve(), data_directory, expected_split=args.split)
    gate = json.loads(args.quality_gate.read_text(encoding="utf-8"))
    resolved_config = _resolved_config(args, suite)
    runtime = await _build_runtime(args, suite, data_directory, resolved_config)
    try:
        cases = list(suite["cases"])
        if args.limit_cases is not None:
            cases = cases[: args.limit_cases]
        for warmup_case in cases[: args.warmup_cases]:
            await evaluate_case(
                runtime,
                warmup_case,
                suite,
                candidate_limit=args.candidate_limit,
            )

        results = []
        for index, case in enumerate(cases, start=1):
            result = await evaluate_case(
                runtime,
                case,
                suite,
                candidate_limit=args.candidate_limit,
            )
            results.append(result)
            print(
                f"[{index:03d}/{len(cases):03d}] {case['id']} "
                f"R@10={result['metrics']['recallAt10']:.3f} "
                f"nDCG@10={result['metrics']['ndcgAt10']:.3f} "
                f"hard={result['integrity']['hardConstraintSatisfaction']:.3f}"
            )

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
        report = {
            "schemaVersion": 2,
            "generatedAt": datetime.now(UTC).isoformat(),
            "suite": {
                key: suite[key]
                for key in (
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
            },
            "run": {
                "git": _git_snapshot(repository),
                "scopedSource": _scoped_source_snapshot(repository),
                "configFingerprint": _fingerprint(resolved_config),
                "latencyProfileFingerprint": _latency_profile_fingerprint(resolved_config),
                "resolvedConfig": resolved_config,
                "stageAvailability": _stage_availability(),
                "evaluatedCases": len(cases),
                "partial": len(cases) != int(suite["caseCount"]),
            },
            "corpus": {
                "profile": manifest.get("profile"),
                "dataVersion": manifest["dataVersion"],
                "datasetSha256": manifest["datasetSha256"],
            },
            "index": runtime.index_report,
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
        if args.output:
            _write_json(args.output, report)
        if args.summary_output:
            _write_json(args.summary_output, concise)
        return report, bool(quality_gate["passed"])
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
            or baseline_suite.get("suiteContractSha256")
            != suite["suiteContractSha256"]
        ):
            raise ValueError(
                "Baseline report uses a different split, case SHA, or suite contract SHA."
            )
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
                    f"{path} increased {current - previous:.6f}; "
                    f"maximum allowed increase is {tolerance}"
                )
        current_latency = _latency_profile_fingerprint(resolved_config)
        baseline_latency = (baseline.get("run") or {}).get("latencyProfileFingerprint")
        if baseline_latency == current_latency:
            for path, ratio in (gate.get("relative") or {}).get("maxRatios", {}).items():
                current = float(_path(summary, path))
                previous = float(_path(baseline_summary, path))
                if previous > 0 and current > previous * float(ratio):
                    failures.append(
                        f"{path} ratio={current / previous:.6f} exceeds {ratio}"
                    )
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
) -> Any:
    embedding = TimedEmbeddingService(_embedding_service(args, resolved_config))
    client = _qdrant_client(args.qdrant_location)
    rag = QdrantRagService(
        client=client,
        embeddings=embedding,
        collection_name=args.collection,
        index_batch_size=args.index_batch_size,
        dataset_sha256=suite["datasetSha256"],
        retrieval_version=suite["retrievalVersion"],
    )
    index_started = time.perf_counter()
    manifest_path = args.index_manifest or _default_index_manifest(
        args.qdrant_location,
        args.collection,
    )
    try:
        if args.reuse_index:
            index_stats = await _validate_reused_index(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
            )
        else:
            await _require_compatible_collection(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
            )
            stats = await rag.sync(
                iter_generated_documents(data_directory),
                data_version=suite["dataVersion"],
            )
            index_stats = stats.as_metadata()
            await _write_index_manifest(
                client,
                args=args,
                suite=suite,
                resolved_config=resolved_config,
                manifest_path=manifest_path,
                point_count=stats.total_documents,
            )
        index_elapsed_ms = (time.perf_counter() - index_started) * 1_000
        info = await client.get_collection(args.collection)
        count = int((await client.count(args.collection, exact=True)).count)
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
            ),
        }
    except Exception:
        await client.close()
        raise

    async def close() -> None:
        await client.close()

    return SimpleNamespace(
        shop_service=GeneratedNycShopToolService(
            data_directory,
            max_candidates=args.discovery_pool_size,
        ),
        rag_service=rag,
        embedding_service=embedding,
        index_report=index_report,
        close=close,
    )


async def _validate_reused_index(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
) -> dict[str, int]:
    if not await client.collection_exists(args.collection):
        raise ValueError("--reuse-index requires an existing collection.")
    info = await client.get_collection(args.collection)
    dimensions = _vector_dimensions(info)
    expected_dimensions = int(resolved_config["embedding"]["dimensions"])
    if dimensions != expected_dimensions:
        raise ValueError(
            f"Existing collection uses {dimensions} dimensions; config requests {expected_dimensions}."
        )
    _require_expected_index_schema(info, expected_dimensions)
    total = int((await client.count(args.collection, exact=True)).count)
    expected = int(suite.get("indexedDocuments") or 0)
    if expected and total != expected:
        raise ValueError(f"Existing collection contains {total} points; suite expects {expected}.")
    matching_filter = models.Filter(
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
        ]
    )
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
    ):
        raise ValueError(
            "Reusing an index requires a matching --index-manifest; point count and vector "
            "dimensions alone cannot identify the embedding implementation."
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
    if not await client.collection_exists(args.collection):
        return
    total = int((await client.count(args.collection, exact=True)).count)
    if not total:
        return
    info = await client.get_collection(args.collection)
    actual_dimensions = _vector_dimensions(info)
    expected_dimensions = int(resolved_config["embedding"]["dimensions"])
    if actual_dimensions != expected_dimensions:
        raise ValueError(
            f"Evaluation collection uses {actual_dimensions} dimensions; "
            f"config requests {expected_dimensions}. Use a new collection."
        )
    _require_expected_index_schema(info, expected_dimensions)
    matching_filter = models.Filter(
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
        ]
    )
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
            "Evaluation collection contains points from another corpus or retrieval version. "
            "Use a new --qdrant-location or --collection; indexes are never repurposed in place."
        )
    if manifest_path.is_file() and not _index_manifest_matches(
        manifest_path,
        args=args,
        suite=suite,
        resolved_config=resolved_config,
    ):
        raise ValueError(
            "Existing index manifest does not match the requested embedding/retrieval config. "
            "Use a new --qdrant-location or --collection."
        )
    if not manifest_path.is_file():
        raise ValueError(
            "An existing collection without a matching sidecar manifest cannot be adopted. "
            "Use a new collection or provide its exact --index-manifest."
        )


async def _write_index_manifest(
    client: AsyncQdrantClient,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
    manifest_path: Path,
    point_count: int,
) -> None:
    info = await client.get_collection(args.collection)
    value = {
        "schemaVersion": 1,
        "collection": args.collection,
        "dataVersion": suite["dataVersion"],
        "datasetSha256": suite["datasetSha256"],
        "retrievalVersion": suite["retrievalVersion"],
        "embedding": resolved_config["embedding"],
        "qdrantEndpointFingerprint": resolved_config["qdrant"].get("endpointFingerprint"),
        "indexBuildVersion": INDEX_BUILD_VERSION,
        "indexBuildSourceFingerprint": resolved_config["retrieval"][
            "indexBuildSourceFingerprint"
        ],
        "indexSchema": _index_schema_snapshot(info),
        "pointCount": point_count,
        "vectorDimensions": _vector_dimensions(info),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _index_manifest_matches(
    path: Path,
    *,
    args: argparse.Namespace,
    suite: dict,
    resolved_config: dict,
) -> bool:
    if not path.is_file():
        return False
    value = json.loads(path.read_text(encoding="utf-8"))
    return all(
        (
            value.get("collection") == args.collection,
            value.get("dataVersion") == suite["dataVersion"],
            value.get("datasetSha256") == suite["datasetSha256"],
            value.get("retrievalVersion") == suite["retrievalVersion"],
            value.get("embedding") == resolved_config["embedding"],
            value.get("qdrantEndpointFingerprint")
            == resolved_config["qdrant"].get("endpointFingerprint"),
            value.get("indexBuildVersion") == INDEX_BUILD_VERSION,
            value.get("indexBuildSourceFingerprint")
            == resolved_config["retrieval"].get("indexBuildSourceFingerprint"),
            value.get("indexSchema")
            == _expected_index_schema(int(resolved_config["embedding"]["dimensions"])),
            int(value.get("vectorDimensions") or 0)
            == int(resolved_config["embedding"]["dimensions"]),
        )
    )


def _embedding_service(args: argparse.Namespace, config: dict) -> EmbeddingService:
    if args.embedding_provider == "openai":
        settings = Settings()
        return OpenAICompatibleEmbeddingService(
            base_url=args.embedding_base_url or settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=str(config["embedding"]["model"]),
            dimensions=int(config["embedding"]["dimensions"]),
        )
    return DeterministicHashEmbeddingService(
        dimensions=int(config["embedding"]["dimensions"])
    )


def _resolved_config(args: argparse.Namespace, suite: dict) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[3]
    if args.embedding_provider == "hash":
        model = args.embedding_model or "deterministic-token-sha256"
        version = args.embedding_version or "hash-v1"
        endpoint_fingerprint = None
    else:
        settings = Settings()
        model = args.embedding_model or settings.embedding_model
        version = args.embedding_version or "provider-revision-unavailable"
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
    qdrant_config: dict[str, Any] = {
        "collection": args.collection,
        "locationKind": _location_kind(args.qdrant_location),
        "reuseIndex": args.reuse_index,
    }
    if qdrant_config["locationKind"] == "remote":
        qdrant_config["endpointFingerprint"] = _endpoint_fingerprint(args.qdrant_location)
    return {
        "retrieval": {
            "version": suite["retrievalVersion"],
            "candidateLimit": args.candidate_limit,
            "discoveryPoolSize": args.discovery_pool_size,
            "mode": args.global_retrieval_mode,
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
            "rerankerProvider": args.reranker_provider,
        },
        "eval": {
            "split": args.split,
            "warmupCases": args.warmup_cases,
            "concurrency": 1,
            "latencyMode": "outer-wall-clock-sequential",
        },
    }


def _stage_availability() -> dict[str, Any]:
    return {
        "structuredSearch": {"available": True, "source": "eval-outer-timer"},
        "candidateRanking": {"available": True, "source": "eval-outer-timer"},
        "evidenceRetrieval": {"available": True, "source": "eval-outer-timer"},
        "embedding": {"available": True, "source": "eval-wrapper"},
        "queryPlanning": {
            "available": False,
            "reason": "current service does not expose an isolated planning timer",
        },
        "qdrant": {
            "available": False,
            "reason": "Qdrant and fusion execute inside candidate/evidence calls",
        },
        "fusion": {
            "available": False,
            "reason": "server-side RRF does not expose a separate timer",
        },
        "rewrite": {"available": False, "reason": "disabled in M0 baseline"},
        "reranker": {"available": False, "reason": "no learned reranker in M0 baseline"},
        "providerUsage": {
            "available": False,
            "reason": "current embedding interface discards provider token/cost metadata",
        },
    }


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
    if args.embedding_provider == "hash":
        if args.embedding_model not in (None, "deterministic-token-sha256"):
            raise ValueError(
                "The Hash provider implementation is fixed to "
                "--embedding-model deterministic-token-sha256."
            )
        if args.embedding_version not in (None, "hash-v1"):
            raise ValueError(
                "The Hash provider implementation is fixed to --embedding-version hash-v1."
            )
    supported = {
        "query_rewrite_provider": (args.query_rewrite_provider, "disabled"),
        "global_retrieval_mode": (args.global_retrieval_mode, "candidate-filtered"),
        "reranker_provider": (args.reranker_provider, "heuristic-multi-signal"),
    }
    for name, (actual, expected) in supported.items():
        if actual != expected:
            raise ValueError(
                f"M0 accepts {name} in the config snapshot but only supports {expected!r}; "
                f"received {actual!r}. Implement the stage before benchmarking it."
            )


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
        raise ValueError(
            "Baseline report must be a complete run with evaluatedCases equal to caseCount."
        )
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
    dense = params.vectors.get("dense") if isinstance(params.vectors, dict) else None
    sparse = (
        params.sparse_vectors.get("lexical")
        if isinstance(params.sparse_vectors, dict)
        else None
    )
    return {
        "dense": {
            "name": "dense",
            "dimensions": int(getattr(dense, "size", 0) or 0),
            "distance": str(getattr(dense, "distance", "")),
        },
        "sparse": {
            "name": "lexical",
            "modifier": str(getattr(sparse, "modifier", "")),
        },
    }


def _expected_index_schema(dimensions: int) -> dict[str, Any]:
    return {
        "dense": {
            "name": "dense",
            "dimensions": dimensions,
            "distance": "Cosine",
        },
        "sparse": {
            "name": "lexical",
            "modifier": "idf",
        },
    }


def _require_expected_index_schema(info: Any, dimensions: int) -> None:
    actual = _index_schema_snapshot(info)
    expected = _expected_index_schema(dimensions)
    if actual != expected:
        raise ValueError(
            f"Existing collection schema {actual!r} does not match expected {expected!r}."
        )


def _default_index_manifest(location: str | Path, collection: str) -> Path:
    value = str(location)
    if value.startswith(("http://", "https://")):
        endpoint = _endpoint_fingerprint(value)[:16]
        collection_id = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:12]
        return (
            EVAL_DIRECTORY.parents[1]
            / ".local"
            / f"rag-v2-remote-index-{endpoint}-{collection_id}.json"
        )
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


def _latency_profile_fingerprint(config: dict) -> str:
    value = {
        "qdrant": config["qdrant"],
        "eval": config["eval"],
        "retrieval": config["retrieval"],
        "embedding": config["embedding"],
        "features": config["features"],
    }
    return _fingerprint(value)


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
    parser.add_argument("--embedding-provider", choices=("hash", "openai"), default="hash")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-version")
    parser.add_argument("--embedding-dimensions", type=int, default=64)
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--query-rewrite-provider", default="disabled")
    parser.add_argument("--global-retrieval-mode", default="candidate-filtered")
    parser.add_argument("--reranker-provider", default="heuristic-multi-signal")
    parser.add_argument("--discovery-pool-size", type=int, default=100)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--warmup-cases", type=int, default=1)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--no-fail", action="store_true")
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    _, passed = await run(args)
    if not passed and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
