from __future__ import annotations

import argparse
import asyncio
import hashlib
import heapq
import json
import logging
import math
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
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingMetadata,
    EmbeddingService,
    EmbeddingUsage,
    OpenAICompatibleEmbeddingService,
    QwenNativeEmbeddingService,
)
from app.rag.nyc_loader import iter_generated_documents
from app.rag.qdrant_store import REQUIRED_PAYLOAD_INDEXES, QdrantRagService
from app.runtime import _validate_data_directory
from app.tools.services import GeneratedNycShopToolService
from evals.rag_v2.compare_m1 import (
    EXPECTED_PROFILES,
    POLICY_VERSION,
    normalized_dev_control,
)
from evals.rag_v2.compare_m1 import (
    compare as compare_m1_reports,
)
from evals.rag_v2.contract import fixture_contract_sha256, suite_contract_sha256
from evals.rag_v2.embedding_profiles import PROFILES, EmbeddingProfile, profile
from evals.rag_v2.metrics import (
    hard_constraint_violations,
    integrity_metrics,
    ranking_metrics,
    rounded,
    summarize_results,
)

EVAL_DIRECTORY = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
INDEX_BUILD_VERSION = "rag-document-transform-v3-m1"
FROZEN_QUALITY_GATE_PATH = EVAL_DIRECTORY / "quality_gate.json"
FROZEN_HASH_BASELINE_PATH = EVAL_DIRECTORY / "baseline.hash64.local.json"
INDEX_BUILD_SOURCE_PATHS = (
    "agent-service/app/rag/embeddings.py",
    "agent-service/app/rag/lexical.py",
    "agent-service/app/rag/models.py",
    "agent-service/app/rag/nyc_loader.py",
    "agent-service/app/rag/qdrant_store.py",
    "agent-service/evals/rag_v2/embedding_profiles.py",
)
EVAL_SOURCE_PATHS = (
    "agent-service/app/domain/models.py",
    "agent-service/app/rag/display_text.py",
    *INDEX_BUILD_SOURCE_PATHS,
    "agent-service/app/rag/query_plan.py",
    "agent-service/app/tools/services.py",
    "agent-service/evals/rag_v2/build_cases.py",
    "agent-service/evals/rag_v2/baseline.hash64.local.json",
    "agent-service/evals/rag_v2/compare_m1.py",
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
    if int(suite.get("schemaVersion") or 0) != 2:
        raise ValueError("RAG v2 suite must use schemaVersion=2.")
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
        raise ValueError(
            "Eval suite suiteContractSha256 does not match its frozen evaluation contract."
        )
    _validate_adversarial_fixture(path.parent, suite)
    _validate_cases(suite)

    validated_data_version, validated_dataset_sha, _ = _validate_data_directory(data_directory)
    if suite.get("dataVersion") != validated_data_version:
        raise ValueError("Eval suite dataVersion does not match the validated corpus files.")
    if suite.get("datasetSha256") != validated_dataset_sha:
        raise ValueError("Eval suite datasetSha256 does not match the validated corpus files.")
    manifest = json.loads(
        (data_directory / "import_manifest.json").read_text(encoding="utf-8")
    )
    for field in ("dataVersion", "datasetSha256"):
        if suite.get(field) != manifest.get(field):
            raise ValueError(
                f"Eval suite {field}={suite.get(field)!r} does not match corpus "
                f"{manifest.get(field)!r}. Regenerate the suite for this exact corpus."
            )
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
            "queryEmbeddingCalls": embedding["queryEmbeddingCalls"],
            "documentEmbeddingCalls": embedding["documentEmbeddingCalls"],
            "embeddedTexts": embedding["embeddedTexts"],
            "rewriteRequests": 0,
            "rerankerRequests": 0,
            "providerUsage": embedding["providerUsage"],
        },
        "orderedCandidates": ordered,
        "retrievalMetadata": {
            "candidatePool": candidate_pool.retrieval_metadata,
            "ranking": ranked.retrieval_metadata,
            "evidence": evidence.retrieval_metadata,
        },
    }


async def run(args: argparse.Namespace) -> tuple[dict, bool]:
    _apply_embedding_profile(args)
    _validate_feature_configuration(args)
    _validate_m1_policy_artifacts(args)
    repository = Path(__file__).resolve().parents[3]
    data_directory = args.data_directory.resolve()
    cases_path = args.cases or EVAL_DIRECTORY / f"cases.{args.split}.json"
    suite, manifest = load_suite(cases_path.resolve(), data_directory, expected_split=args.split)
    gate = json.loads(args.quality_gate.read_text(encoding="utf-8"))
    resolved_config = _resolved_config(args, suite)
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
            )
        runtime.embedding_service.clear_query_cache()

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
        fallback_count = sum(
            bool(
                ((result.get("retrievalMetadata") or {}).get(stage) or {}).get(
                    "embeddingFallback"
                )
            )
            for result in results
            for stage in ("ranking", "evidence")
        )
        if args.embedding_provider != "hash" and fallback_count:
            quality_gate["failures"].append(
                f"Formal embedding evaluation observed {fallback_count} sparse fallbacks."
            )
            quality_gate["passed"] = False
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
                "stageAvailability": _stage_availability(resolved_config),
                "policyArtifacts": _policy_artifact_snapshot(args),
                "evaluatedCases": len(cases),
                "partial": len(cases) != int(suite["caseCount"]),
                "embeddingFallbackCount": fallback_count,
            },
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
        if args.output:
            _write_json(args.output, report)
        if args.summary_output:
            _write_json(args.summary_output, concise)
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
            raise ValueError(
                f"Evaluation collection contains {count} points; expected {expected_points}."
            )
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
            "preflight": preflight,
        }
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

    return SimpleNamespace(
        shop_service=GeneratedNycShopToolService(
            data_directory,
            max_candidates=args.discovery_pool_size,
        ),
        rag_service=rag,
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
    await _require_qdrant_server_contract(args.qdrant_location)
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
            raise ValueError(
                "--index-action resume requires an exact state=building index manifest."
            )
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
        raise ValueError(
            "Index manifest already exists; refusing paid preflight before an invalid build."
        )
    if action == "resume" and not _index_manifest_matches(
        manifest_path,
        args=args,
        suite=suite,
        resolved_config=resolved_config,
        required_state="building",
    ):
        raise ValueError(
            "Resume requires an exact state=building manifest before any paid preflight."
        )
    client = _qdrant_client(args.qdrant_location)
    try:
        exists = await client.collection_exists(args.collection)
        if action == "build" and exists:
            raise ValueError(
                "Collection already exists; refusing paid preflight for a new build."
            )
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
        "indexBuildSourceFingerprint": resolved_config["retrieval"][
            "indexBuildSourceFingerprint"
        ],
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
        required_state != "complete"
        or int(value.get("pointCount") or 0) == expected_points
    )
    return all(
        (
            value.get("collection") == args.collection,
            value.get("state") == required_state,
            value.get("dataVersion") == suite["dataVersion"],
            value.get("datasetSha256") == suite["datasetSha256"],
            value.get("retrievalVersion") == suite["retrievalVersion"],
            value.get("embedding") == resolved_config["embedding"],
            value.get("qdrantEndpointFingerprint")
            == resolved_config["qdrant"].get("endpointFingerprint"),
            value.get("indexBuildVersion") == INDEX_BUILD_VERSION,
            value.get("indexBuildSourceFingerprint")
            == resolved_config["retrieval"].get("indexBuildSourceFingerprint"),
            int(value.get("expectedPointCount") or 0) == expected_points,
            complete_count_matches,
            value.get("indexSchema")
            == _expected_index_schema(
                int(resolved_config["embedding"]["dimensions"]),
                include_payload_indexes=(
                    resolved_config["qdrant"]["locationKind"] == "remote"
                ),
            ),
            int(value.get("vectorDimensions") or 0)
            == int(resolved_config["embedding"]["dimensions"]),
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
        raise ValueError(
            f"Embedding profile {profile_id!r} conflicts with: {', '.join(conflicts)}."
        )
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
                args.embedding_base_url
                or settings.qwen_embedding_base_url
                or settings.embedding_base_url
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
                args.embedding_base_url
                or settings.qwen_embedding_base_url
                or settings.embedding_base_url
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
                    args.max_provider_cost_usd
                    / selected.price_usd_per_million_tokens
                    * 1_000_000
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


def _stage_availability(resolved_config: dict) -> dict[str, Any]:
    real_embedding = resolved_config["embedding"]["provider"] != "hash"
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
            "available": real_embedding,
            "source": "provider-response-usage" if real_embedding else "not-applicable-hash",
        },
    }


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
        corpus["totalCharacters"]
        * document_usage.total_tokens
        / corpus["sampleCharacters"]
        * 1.15
    )
    projected_query_tokens = math.ceil(
        query_usage.total_tokens
        / len(query_examples)
        * int(suite["caseCount"])
        * 1.15
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
        content_type_counts[document.content_type] = (
            content_type_counts.get(document.content_type, 0) + 1
        )
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
    return EmbeddingUsage(
        **{
            key: sum(getattr(value, key) for value in values)
            for key in fields
        }
    )


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
        server_ready = (
            status.casefold() in {"green", "ok"}
            and optimizer_status.casefold() in {"ok", "green"}
        )
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


async def _require_qdrant_server_contract(location: str | Path) -> None:
    if _location_kind(location) != "remote":
        return
    metadata = await _qdrant_server_metadata(location)
    version = str(metadata.get("version") or "")
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except (TypeError, ValueError):
        raise ValueError(
            "Qdrant Server metadata/version is unavailable; refusing paid preflight."
        ) from None
    if major != 1 or minor < 19:
        raise ValueError(
            f"M1 requires Qdrant Server 1.19+ in the 1.x series; observed {version!r}."
        )


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
    action = _index_action(args)
    if args.preflight_only and args.provider_smoke:
        raise ValueError("Choose either --preflight-only or --provider-smoke, not both.")
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
            raise ValueError(
                "Paid index construction requires the explicit --allow-paid-index-build flag."
            )
        if args.limit_cases is not None and action in {"build", "resume"}:
            raise ValueError(
                "--limit-cases does not limit indexing and is forbidden during a paid build; "
                "use --provider-smoke before the full build."
            )
        if args.max_provider_cost_usd is None or args.max_provider_cost_usd <= 0:
            raise ValueError("Paid profiles require a positive provider cost cap.")
        if args.embedding_query_instruct:
            raise ValueError(
                "The frozen M1 comparison does not enable a Qwen query instruction."
            )
        if args.split == "test" and not (args.preflight_only or args.provider_smoke):
            if action != "reuse":
                raise ValueError("The M1 policy holdout must reuse the selected Dev index.")
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


def _validate_m1_policy_artifacts(args: argparse.Namespace) -> None:
    if args.embedding_provider == "hash" or args.preflight_only or args.provider_smoke:
        return
    if args.baseline_report is None:
        raise ValueError(
            "Formal M1 evaluation requires the frozen Hash baseline via --baseline-report."
        )
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
            raise ValueError(
                f"Formal M1 {label} must match the committed frozen artifact exactly."
            )


def _policy_artifact_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "qualityGateSha256": _file_sha256(args.quality_gate),
        "baselineReportSha256": (
            _file_sha256(args.baseline_report) if args.baseline_report else None
        ),
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
        raise ValueError(
            "The M1 policy holdout requires --winner-manifest and --allow-policy-holdout."
        )
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
        "baselineReportSha256": (
            (frozen_artifacts.get("baselineManifest") or {}).get("sha256")
        ),
    }
    if observed_artifacts != expected_artifacts:
        raise ValueError("Winner manifest does not bind the committed M1 policy artifacts.")
    expected_control = normalized_dev_control(resolved_config, include_collection=True)
    if winner.get("winnerDevControl") != expected_control:
        raise ValueError(
            "Holdout retrieval, runtime, collection, or Qdrant endpoint drifted from Dev."
        )
    receipt_path = _holdout_receipt_path(args.winner_manifest, suite)
    if receipt_path.exists():
        raise FileExistsError(
            f"The M1 policy holdout has already been attempted: {receipt_path}"
        )


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
        raise FileExistsError(
            f"The M1 policy holdout has already been attempted: {path}"
        ) from None
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
    dense = params.vectors.get("dense") if isinstance(params.vectors, Mapping) else None
    sparse = (
        params.sparse_vectors.get("lexical")
        if isinstance(params.sparse_vectors, Mapping)
        else None
    )
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
            field: _enum_value(
                getattr(payload_schema.get(field), "data_type", payload_schema.get(field))
            )
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
            field: _enum_value(schema)
            for field, schema in sorted(REQUIRED_PAYLOAD_INDEXES.items())
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
    parser.add_argument("--global-retrieval-mode", default="candidate-filtered")
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
    parser.add_argument("--no-fail", action="store_true")
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    _, passed = await run(args)
    if not passed and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
