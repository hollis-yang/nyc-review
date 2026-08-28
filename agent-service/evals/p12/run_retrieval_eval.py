from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from qdrant_client import AsyncQdrantClient, models

from app.config import Settings
from app.domain.models import UserConstraints
from app.rag.embeddings import DeterministicHashEmbeddingService
from app.rag.lexical import normalized_merchant_name
from app.rag.qdrant_store import QdrantRagService
from app.runtime import AgentRuntime
from app.tools.services import GeneratedNycShopToolService, neighborhood_matches

EVAL_DIRECTORY = Path(__file__).resolve().parent


def load_suite(path: Path, data_directory: Path) -> tuple[dict, dict]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads(
        (data_directory / "import_manifest.json").read_text(encoding="utf-8")
    )
    for field in ("dataVersion", "datasetSha256"):
        if suite.get(field) != manifest.get(field):
            raise ValueError(
                f"Eval suite {field}={suite.get(field)!r} does not match corpus "
                f"{manifest.get(field)!r}. Generate a current-corpus suite or use the frozen P11.5 bundle."
            )
    if int(suite.get("caseCount") or 0) != len(suite.get("cases") or []):
        raise ValueError("Eval suite caseCount does not match its case list.")
    return suite, manifest


async def evaluate_case(runtime: AgentRuntime, case: dict, suite: dict) -> dict:
    constraints = UserConstraints.model_validate(case["constraints"])
    started = time.perf_counter()
    candidate_pool = await runtime.shop_service.search(constraints)
    ranked = await runtime.rag_service.rank_candidates(
        constraints,
        candidate_pool,
        limit=10,
    )
    evidence = await runtime.rag_service.retrieve(constraints, ranked)
    latency_ms = round((time.perf_counter() - started) * 1_000, 3)

    expected = set(case["expectedExternalIds"])
    returned = {
        candidate.external_id
        for candidate in ranked.candidates
        if candidate.external_id
    }
    cited = {item.shop_id for item in evidence.evidence if item.citations}
    citations = [
        citation
        for item in evidence.evidence
        for citation in item.citations
    ]
    external_ids = [
        candidate.external_id
        for candidate in ranked.candidates
        if candidate.external_id
    ]
    brands = [normalized_merchant_name(candidate.name) for candidate in ranked.candidates]
    duplicate_identity_count = len(external_ids) - len(set(external_ids))
    excessive_brand_count = sum(max(0, brands.count(brand) - 2) for brand in set(brands) if brand)
    constraints_ok = [
        candidate.category == constraints.category
        and (
            not constraints.neighborhood
            or neighborhood_matches(candidate.neighborhood, constraints.neighborhood)
        )
        and set(constraints.desired_tags) <= set(candidate.tags)
        for candidate in ranked.candidates
    ]
    version_mismatches = sum(
        citation.data_version != suite["dataVersion"]
        or citation.dataset_sha256 != suite["datasetSha256"]
        for citation in citations
    )
    return {
        "id": case["id"],
        "language": case["language"],
        "query": case["query"],
        "expectedRelevant": len(expected),
        "candidatePool": len(candidate_pool.candidates),
        "returned": len(ranked.candidates),
        "recallAt10": round(len(expected & returned) / len(expected), 4) if expected else 1.0,
        "evidenceCoverage": (
            round(len({item.shop_id for item in ranked.candidates} & cited) / len(ranked.candidates), 4)
            if ranked.candidates
            else 0.0
        ),
        "structuredConstraintSatisfaction": (
            round(sum(constraints_ok) / len(constraints_ok), 4) if constraints_ok else 0.0
        ),
        "duplicateIdentityCount": duplicate_identity_count,
        "excessiveBrandCount": excessive_brand_count,
        "securityLeakageCount": sum(citation.security_test for citation in citations),
        "versionMismatchCount": version_mismatches,
        "citationCount": len(citations),
        "retrievalLatencyMs": latency_ms,
        "retrievalMetadata": ranked.retrieval_metadata,
    }


def summarize(results: list[dict]) -> dict:
    case_count = max(1, len(results))
    citation_count = sum(item["citationCount"] for item in results)
    return {
        "cases": len(results),
        "englishCases": sum(item["language"] == "en" for item in results),
        "chineseCases": sum(item["language"] == "zh" for item in results),
        "meanRecallAt10": round(statistics.fmean(item["recallAt10"] for item in results), 4),
        "evidenceCoverage": round(
            statistics.fmean(item["evidenceCoverage"] for item in results), 4
        ),
        "structuredConstraintSatisfaction": round(
            statistics.fmean(item["structuredConstraintSatisfaction"] for item in results), 4
        ),
        "duplicateMerchantRate": round(
            sum(item["duplicateIdentityCount"] for item in results) / case_count,
            4,
        ),
        "excessiveBrandCount": sum(item["excessiveBrandCount"] for item in results),
        "securityLeakageCount": sum(item["securityLeakageCount"] for item in results),
        "versionMismatchRate": round(
            sum(item["versionMismatchCount"] for item in results) / max(1, citation_count),
            4,
        ),
        "p95RetrievalLatencyMs": percentile(
            [item["retrievalLatencyMs"] for item in results], 0.95
        ),
    }


def evaluate_gate(summary: dict, gate: dict) -> list[str]:
    failures: list[str] = []
    minimums = {
        "meanRecallAt10": "minMeanRecallAt10",
        "evidenceCoverage": "minEvidenceCoverage",
        "structuredConstraintSatisfaction": "minStructuredConstraintSatisfaction",
    }
    maximums = {
        "duplicateMerchantRate": "maxDuplicateMerchantRate",
        "securityLeakageCount": "maxSecurityLeakageCount",
        "versionMismatchRate": "maxVersionMismatchRate",
        "p95RetrievalLatencyMs": "maxP95RetrievalLatencyMs",
    }
    for metric, threshold in minimums.items():
        if float(summary[metric]) < float(gate[threshold]):
            failures.append(f"{metric}={summary[metric]} is below {gate[threshold]}")
    for metric, threshold in maximums.items():
        if float(summary[metric]) > float(gate[threshold]):
            failures.append(f"{metric}={summary[metric]} exceeds {gate[threshold]}")
    if int(summary["excessiveBrandCount"]) > 0:
        failures.append(
            f"excessiveBrandCount={summary['excessiveBrandCount']} exceeds 0"
        )
    return failures


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return round(ordered[index], 3)


async def run(args) -> tuple[dict, bool]:
    data_directory = args.data_directory.resolve()
    suite, manifest = load_suite(args.cases.resolve(), data_directory)
    gate = json.loads(args.quality_gate.read_text(encoding="utf-8"))
    runtime = await _build_runtime(args, suite, data_directory)
    try:
        results = []
        for index, case in enumerate(suite["cases"], start=1):
            result = await evaluate_case(runtime, case, suite)
            results.append(result)
            print(
                f"[{index:02d}/{len(suite['cases']):02d}] {case['id']} "
                f"recall@10={result['recallAt10']:.2f} "
                f"evidence={result['evidenceCoverage']:.2f}"
            )
        summary = summarize(results)
        failures = evaluate_gate(summary, gate)
        report = {
            "suite": {
                key: suite[key]
                for key in (
                    "suite",
                    "retrievalVersion",
                    "dataVersion",
                    "datasetSha256",
                    "caseCount",
                    "caseSha256",
                )
            },
            "index": runtime.rag_index_stats,
            "corpusProfile": manifest.get("profile"),
            "qualityGate": {
                "passed": not failures,
                "failures": failures,
                "thresholds": gate,
            },
            "summary": summary,
            "results": results,
        }
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        print(
            json.dumps(
                {
                    "suite": report["suite"],
                    "index": report["index"],
                    "qualityGate": report["qualityGate"],
                    "summary": report["summary"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return report, not failures
    finally:
        await runtime.close()


async def _build_runtime(args, suite: dict, data_directory: Path):
    if not args.reuse_index:
        await _require_isolated_collection(args, suite)
        return await AgentRuntime.create(
            Settings(
                adapter="mock",
                rag_adapter="qdrant",
                qdrant_location=str(args.qdrant_location),
                qdrant_collection=args.collection,
                retrieval_version=suite["retrievalVersion"],
                rag_data_directory=data_directory,
                rag_index_batch_size=args.index_batch_size,
                embedding_provider="hash",
                model_provider="heuristic",
                discovery_pool_size=100,
                max_candidates=10,
                run_store_path=":memory:",
            )
        )

    client = AsyncQdrantClient(path=str(args.qdrant_location))
    rag = QdrantRagService(
        client=client,
        embeddings=DeterministicHashEmbeddingService(dimensions=64),
        collection_name=args.collection,
        index_batch_size=args.index_batch_size,
        dataset_sha256=suite["datasetSha256"],
        retrieval_version=suite["retrievalVersion"],
    )
    if not await client.collection_exists(args.collection):
        await client.close()
        raise ValueError("--reuse-index requires an existing P12 collection.")
    count = (await client.count(args.collection, exact=True)).count
    expected = int(suite.get("indexedDocuments") or 0)
    if expected and count != expected:
        await client.close()
        raise ValueError(
            f"Existing collection contains {count} points; frozen suite expects {expected}."
        )

    async def close() -> None:
        await client.close()

    return SimpleNamespace(
        shop_service=GeneratedNycShopToolService(data_directory, max_candidates=100),
        rag_service=rag,
        rag_index_stats={"total": count, "reused": count},
        close=close,
    )


async def _require_isolated_collection(args, suite: dict) -> None:
    """Refuse to benchmark a collection containing another corpus.

    The application service can intentionally retain multiple dataset scopes
    in one collection and filters them at query time. An evaluation collection
    is different: foreign points distort local-mode latency and make the point
    count in the report misleading. Require a new path/collection rather than
    silently appending another 145k-point corpus.
    """

    client = AsyncQdrantClient(path=str(args.qdrant_location))
    try:
        if not await client.collection_exists(args.collection):
            return
        total = (await client.count(args.collection, exact=True)).count
        if not total:
            return
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
            ]
        )
        matching = (
            await client.count(
                args.collection,
                count_filter=matching_filter,
                exact=True,
            )
        ).count
        if matching != total:
            raise ValueError(
                "Evaluation collection contains points from another corpus "
                f"({matching}/{total} match). Use a new --qdrant-location or "
                "--collection so latency and point-count gates remain isolated."
            )
    finally:
        await client.close()


def build_parser() -> argparse.ArgumentParser:
    repository = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Run the P12 frozen RAG quality gate.")
    parser.add_argument("--cases", type=Path, default=EVAL_DIRECTORY / "cases.json")
    parser.add_argument("--quality-gate", type=Path, default=EVAL_DIRECTORY / "quality_gate.json")
    parser.add_argument(
        "--data-directory",
        type=Path,
        default=repository / "data" / "generated" / "nyc-real-p11-5-full",
    )
    parser.add_argument(
        "--qdrant-location",
        type=Path,
        default=repository / "agent-service" / ".local" / "qdrant-p12",
    )
    parser.add_argument("--collection", default="nyc_review_content_v2")
    parser.add_argument("--index-batch-size", type=int, default=128)
    parser.add_argument(
        "--reuse-index",
        action="store_true",
        help="Skip corpus synchronization after a complete isolated index already exists.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-fail", action="store_true")
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    _, passed = await run(args)
    if not passed and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
