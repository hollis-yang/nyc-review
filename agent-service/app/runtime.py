from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from app.actions.service import AgentActionService, HttpActionGateway, InMemoryActionGateway
from app.config import Settings
from app.domain.models import AgentMode
from app.graph.workflow import WorkflowServices, build_multi_agent_graph, build_single_agent_graph
from app.model_gateway import HeuristicModelGateway, OpenAICompatibleModelGateway
from app.rag.candidate_discovery import (
    CandidateDiscovery,
    GlobalHybridCandidateDiscovery,
    LegacyCandidateDiscovery,
)
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    EmbeddingService,
    OpenAICompatibleEmbeddingService,
    QwenNativeEmbeddingService,
)
from app.rag.global_retrieval import GlobalRetrievalScope, QdrantGlobalDocumentRetriever
from app.rag.nyc_loader import iter_generated_documents
from app.rag.qdrant_store import QdrantRagService
from app.rag.query_rewriter import (
    DisabledQueryRewriter,
    OpenAICompatibleQueryRewriter,
    QueryRewriteProvider,
)
from app.rag.reranker import (
    CandidateReranker,
    HttpCrossEncoderReranker,
    MerchantRerankTextBuilder,
)
from app.runs.manager import AgentRunManager
from app.runs.store import SQLiteRunStore
from app.security import SlidingWindowRateLimiter
from app.tools.services import (
    GeneratedNycShopToolService,
    HaversineItineraryService,
    HttpShopToolService,
    InMemoryRagService,
    MockShopToolService,
)


@dataclass
class AgentRuntime:
    workflow: Any
    workflows: dict[AgentMode, Any]
    adapter_name: str
    rag_name: str
    indexed_documents: int = 0
    data_version: str | None = None
    dataset_sha256: str | None = None
    source_counts: dict[str, int] = field(default_factory=dict)
    rag_index_stats: dict[str, int] = field(default_factory=dict)
    retrieval_version: str = "p12-rag-v1"
    qdrant_client: AsyncQdrantClient | None = None
    run_manager: AgentRunManager | None = None
    model_provider: str = "heuristic"
    action_service: AgentActionService | None = None
    rate_limiter: SlidingWindowRateLimiter | None = None
    metrics_token: str = ""
    settings: Settings | None = None
    shop_service: Any = None
    rag_service: Any = None
    itinerary_service: Any = None
    embedding_service: EmbeddingService | None = None
    query_rewriter: QueryRewriteProvider | None = None
    reranker: CandidateReranker | None = None
    candidate_discovery: CandidateDiscovery | None = None
    _closed: bool = field(default=False, init=False, repr=False)

    @classmethod
    async def create(cls, settings: Settings) -> AgentRuntime:
        shops = _build_shop_service(settings)
        qdrant_client: AsyncQdrantClient | None = None
        run_store: SQLiteRunStore | None = None
        run_manager: AgentRunManager | None = None
        indexed_documents = 0
        data_version: str | None = None
        dataset_sha256: str | None = None
        source_counts: dict[str, int] = {}
        rag_index_stats: dict[str, int] = {}
        embedding_service: EmbeddingService | None = None
        query_rewriter: QueryRewriteProvider | None = None
        reranker: CandidateReranker | None = None
        if settings.rag_data_directory is not None:
            data_version, dataset_sha256, source_counts = _validate_data_directory(
                settings.rag_data_directory.resolve()
            )

        try:
            if settings.rag_adapter == "qdrant":
                qdrant_client = _build_qdrant_client(
                    settings.qdrant_location,
                    api_key=settings.qdrant_api_key.get_secret_value(),
                )
                embedding_service = _build_embedding_service(settings)
                rag = QdrantRagService(
                    client=qdrant_client,
                    embeddings=embedding_service,
                    collection_name=settings.qdrant_collection,
                    index_batch_size=settings.rag_index_batch_size,
                    dataset_sha256=dataset_sha256,
                    retrieval_version=settings.retrieval_version,
                    allow_sparse_fallback=_embedding_sparse_fallback_enabled(settings),
                )
                if settings.rag_data_directory is not None:
                    data_directory = settings.rag_data_directory.resolve()
                    index_stats = await rag.sync(
                        iter_generated_documents(data_directory),
                        data_version=data_version,
                    )
                    indexed_documents = index_stats.total_documents
                    rag_index_stats = index_stats.as_metadata()
            else:
                rag = InMemoryRagService(
                    data_version=data_version,
                    dataset_sha256=dataset_sha256,
                )

            itinerary = HaversineItineraryService()
            if settings.global_retrieval_enabled:
                if qdrant_client is None or embedding_service is None:
                    raise RuntimeError("Global retrieval requires Qdrant and an embedding service.")
                if not data_version or not dataset_sha256:
                    raise ValueError(
                        "Global retrieval requires verified data_version and dataset_sha256 values."
                    )
                scope = GlobalRetrievalScope(
                    collection_name=settings.qdrant_collection,
                    data_version=data_version,
                    dataset_sha256=dataset_sha256,
                    retrieval_version=settings.retrieval_version,
                    embedding_identity=embedding_service.metadata.identity,
                )
                global_retriever = QdrantGlobalDocumentRetriever(
                    qdrant_client,
                    embedding_service,
                    scope,
                    document_limit=settings.global_retrieval_document_limit,
                )
                query_rewriter = _build_query_rewriter(settings)
                reranker = _build_reranker(settings)
                candidate_discovery = GlobalHybridCandidateDiscovery(
                    shops,
                    rag,
                    global_retriever,
                    document_limit=settings.global_retrieval_document_limit,
                    hydration_limit=settings.global_retrieval_hydration_limit,
                    fusion_pool_limit=settings.global_retrieval_fusion_pool_limit,
                    hydration_concurrency=settings.global_retrieval_hydration_concurrency,
                    branch_timeout_seconds=settings.global_retrieval_branch_timeout_seconds,
                    documents_per_merchant=settings.global_retrieval_documents_per_merchant,
                    rrf_k=settings.global_retrieval_rrf_k,
                    brand_cap=settings.global_retrieval_brand_cap,
                    query_rewriter=query_rewriter,
                    reranker=reranker,
                    rerank_text_builder=MerchantRerankTextBuilder(
                        max_characters=settings.reranker_max_document_characters,
                        max_evidence=settings.reranker_max_evidence_excerpts,
                        max_evidence_characters=settings.reranker_max_evidence_characters,
                    ),
                    reranker_candidate_limit=settings.reranker_candidate_limit,
                )
            else:
                candidate_discovery = LegacyCandidateDiscovery(shops, rag)
            services = WorkflowServices(
                shops=shops,
                rag=rag,
                itinerary=itinerary,
                final_candidate_limit=settings.max_candidates,
                candidate_discovery=candidate_discovery,
            )
            workflows = {
                AgentMode.SINGLE: build_single_agent_graph(services),
                AgentMode.MULTI: build_multi_agent_graph(services),
            }
            runtime = cls(
                workflow=workflows[AgentMode.MULTI],
                workflows=workflows,
                adapter_name=settings.adapter,
                rag_name=settings.rag_adapter,
                indexed_documents=indexed_documents,
                data_version=data_version,
                dataset_sha256=dataset_sha256,
                source_counts=source_counts,
                rag_index_stats=rag_index_stats,
                retrieval_version=settings.retrieval_version,
                qdrant_client=qdrant_client,
                model_provider=settings.model_provider,
                action_service=AgentActionService(
                    HttpActionGateway(
                        settings.backend_base_url,
                        fallback_authorization=settings.backend_auth_token,
                    )
                    if settings.adapter == "http"
                    else InMemoryActionGateway()
                ),
                rate_limiter=SlidingWindowRateLimiter(settings.runs_per_minute),
                metrics_token=settings.metrics_token,
                settings=settings,
                shop_service=shops,
                rag_service=rag,
                itinerary_service=itinerary,
                embedding_service=embedding_service,
                query_rewriter=query_rewriter,
                reranker=reranker,
                candidate_discovery=candidate_discovery,
            )
            model_gateway = _build_model_gateway(settings)
            run_store = SQLiteRunStore(settings.run_store_path)
            run_manager = AgentRunManager(
                runtime,
                run_store,
                model_gateway,
                max_recovery_attempts=settings.max_recovery_attempts,
            )
            runtime.run_manager = run_manager
            await run_manager.recover()
            return runtime
        except BaseException:
            callbacks: list[Callable[[], Awaitable[None]]] = []
            if run_manager is not None:
                callbacks.append(run_manager.close)
            elif run_store is not None:
                callbacks.append(run_store.close)
            if query_rewriter is not None:
                callbacks.append(query_rewriter.aclose)
            if reranker is not None:
                callbacks.append(reranker.aclose)
            if embedding_service is not None:
                callbacks.append(embedding_service.aclose)
            if qdrant_client is not None:
                callbacks.append(qdrant_client.close)
            await _close_async_callbacks(callbacks, suppress_errors=True)
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        callbacks: list[Callable[[], Awaitable[None]]] = []
        if self.run_manager is not None:
            callbacks.append(self.run_manager.close)
        if self.query_rewriter is not None:
            callbacks.append(self.query_rewriter.aclose)
        if self.reranker is not None:
            callbacks.append(self.reranker.aclose)
        if self.embedding_service is not None:
            callbacks.append(self.embedding_service.aclose)
        if self.qdrant_client is not None:
            callbacks.append(self.qdrant_client.close)
        # Mark closed before awaiting so a repeated call cannot close the same
        # clients twice. References remain available for post-shutdown metrics
        # and task-state assertions.
        await _close_async_callbacks(callbacks)


async def _close_async_callbacks(
    callbacks: list[Callable[[], Awaitable[None]]],
    *,
    suppress_errors: bool = False,
) -> None:
    errors: list[BaseException] = []
    for callback in callbacks:
        try:
            await callback()
        except BaseException as exc:
            errors.append(exc)
    if suppress_errors or not errors:
        return
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup("Multiple runtime resources failed to close.", errors)


def _build_shop_service(settings: Settings):
    if settings.adapter == "http":
        return HttpShopToolService(
            base_url=settings.backend_base_url,
            auth_token=settings.backend_auth_token,
            max_candidates=settings.discovery_pool_size,
        )
    if settings.rag_data_directory is not None:
        data_directory = settings.rag_data_directory.resolve()
        _validate_data_directory(data_directory)
        return GeneratedNycShopToolService(data_directory, settings.discovery_pool_size)
    return MockShopToolService()


def _embedding_sparse_fallback_enabled(settings: Settings) -> bool:
    """Global retrieval requires dense ranking failures to remain fail-closed."""

    return settings.embedding_sparse_fallback and not settings.global_retrieval_enabled


def _build_qdrant_client(location: str, *, api_key: str = "") -> AsyncQdrantClient:
    if location.startswith(("http://", "https://")):
        return AsyncQdrantClient(url=location, api_key=api_key or None)
    if location == ":memory:":
        return AsyncQdrantClient(location=location)
    return AsyncQdrantClient(path=location)


def _build_embedding_service(settings: Settings):
    if settings.embedding_provider == "openai":
        return OpenAICompatibleEmbeddingService(
            base_url=settings.embedding_base_url,
            api_key=(
                settings.openai_embedding_api_key.get_secret_value()
                or settings.embedding_api_key.get_secret_value()
            ),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            version=settings.embedding_version or settings.embedding_model,
            batch_size=settings.embedding_batch_size,
            max_concurrency=settings.embedding_max_concurrency,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
            max_batch_characters=settings.embedding_max_batch_characters,
            query_cache_size=settings.embedding_query_cache_size,
            query_cache_ttl_seconds=settings.embedding_query_cache_ttl_seconds,
            query_prefix=settings.embedding_query_prefix,
            document_prefix=settings.embedding_document_prefix,
            max_total_tokens=settings.embedding_max_total_tokens,
        )
    if settings.embedding_provider == "qwen":
        return QwenNativeEmbeddingService(
            base_url=settings.qwen_embedding_base_url or settings.embedding_base_url,
            api_key=(
                settings.qwen_embedding_api_key.get_secret_value()
                or settings.embedding_api_key.get_secret_value()
            ),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            version=settings.embedding_version or settings.embedding_model,
            batch_size=settings.embedding_batch_size,
            max_concurrency=settings.embedding_max_concurrency,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
            max_batch_characters=settings.embedding_max_batch_characters,
            query_cache_size=settings.embedding_query_cache_size,
            query_cache_ttl_seconds=settings.embedding_query_cache_ttl_seconds,
            query_prefix=settings.embedding_query_prefix,
            document_prefix=settings.embedding_document_prefix,
            query_instruct=settings.embedding_query_instruct,
            max_total_tokens=settings.embedding_max_total_tokens,
        )
    return DeterministicHashEmbeddingService(
        dimensions=settings.embedding_dimensions,
        version=settings.embedding_version or "hash-v1",
    )


def _build_query_rewriter(settings: Settings) -> QueryRewriteProvider | None:
    """Build M3 rewriting only when its explicit feature flag is enabled."""

    provider = settings.query_rewrite_provider
    if provider == "disabled":
        return None

    fallback = DisabledQueryRewriter(
        prompt_version=settings.query_rewrite_prompt_version,
    )
    dedicated_key = settings.query_rewrite_api_key.get_secret_value()
    if provider == "openai":
        base_url = settings.query_rewrite_base_url or "https://api.openai.com/v1"
        api_key = dedicated_key or settings.openai_embedding_api_key.get_secret_value()
        model = settings.query_rewrite_model or "gpt-4o-mini-2024-07-18"
    else:
        base_url = settings.query_rewrite_base_url or settings.model_base_url
        api_key = dedicated_key or settings.model_api_key
        model = settings.query_rewrite_model or settings.model_name

    return OpenAICompatibleQueryRewriter(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        fallback=fallback,
        prompt_version=settings.query_rewrite_prompt_version,
        max_queries=settings.query_rewrite_max_queries,
        timeout_seconds=settings.query_rewrite_timeout_seconds,
        max_concurrency=settings.query_rewrite_max_concurrency,
        cache_size=settings.query_rewrite_cache_size,
        cache_ttl_seconds=settings.query_rewrite_cache_ttl_seconds,
        max_input_characters=settings.query_rewrite_max_input_characters,
        max_output_tokens=settings.query_rewrite_max_output_tokens,
    )


def _build_reranker(settings: Settings) -> CandidateReranker | None:
    """Build M4 only behind its explicit query-side feature flag."""

    if settings.reranker_provider == "disabled":
        return None
    api_key = (
        settings.reranker_api_key.get_secret_value().strip()
        or settings.qwen_embedding_api_key.get_secret_value().strip()
    )
    if not api_key:
        raise ValueError(
            "Qwen reranking requires a configured reranker or DashScope API key."
        )
    base_url = settings.reranker_base_url or _qwen_reranker_base_url(
        settings.qwen_embedding_base_url
    )
    return HttpCrossEncoderReranker(
        provider=settings.reranker_provider,
        base_url=base_url,
        api_key=api_key,
        model=settings.reranker_model,
        instruct=settings.reranker_instruct,
        version=settings.reranker_version or settings.reranker_model,
        timeout_seconds=settings.reranker_timeout_seconds,
        max_concurrency=settings.reranker_max_concurrency,
        max_candidates=settings.reranker_candidate_limit,
        max_retries=settings.reranker_max_retries,
        cache_size=settings.reranker_cache_size,
        cache_ttl_seconds=settings.reranker_cache_ttl_seconds,
        circuit_failure_threshold=settings.reranker_circuit_failure_threshold,
        circuit_recovery_seconds=settings.reranker_circuit_cooldown_seconds,
        input_cost_per_million_tokens=(
            settings.reranker_input_price_usd_per_million_tokens
        ),
    )


def _qwen_reranker_base_url(embedding_base_url: str) -> str:
    """Derive only the documented workspace rerank endpoint, never another provider."""

    normalized = embedding_base_url.strip().rstrip("/")
    suffix = "/compatible-mode/v1"
    if normalized.endswith("/compatible-api/v1"):
        return normalized
    if normalized.endswith(suffix):
        return f"{normalized[: -len(suffix)]}/compatible-api/v1"
    raise ValueError(
        "qwen reranking requires NYC_REVIEW_AGENT_RERANKER_BASE_URL or a "
        "DASHSCOPE_BASE_URL ending in /compatible-mode/v1."
    )


def _build_model_gateway(settings: Settings):
    heuristic = HeuristicModelGateway()
    if settings.model_provider == "heuristic":
        return heuristic
    return OpenAICompatibleModelGateway(
        provider=settings.model_provider,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        fallback=heuristic if settings.model_fallback_to_heuristic else None,
    )


def _validate_data_directory(
    data_directory: Path,
) -> tuple[str | None, str | None, dict[str, int]]:
    required = ["shops.json", "shop_reviews.json", "blogs.json", "blog_comments.json"]
    missing = [name for name in required if not (data_directory / name).is_file()]
    if missing:
        raise FileNotFoundError(f"RAG data directory {data_directory} is missing: {', '.join(missing)}")
    with (data_directory / "shops.json").open(encoding="utf-8") as handle:
        shops = json.load(handle)
    if not isinstance(shops, list):
        raise ValueError("Generated shops.json must contain a list.")
    data_versions = {shop.get("dataVersion") for shop in shops if shop.get("dataVersion")}
    if len(data_versions) > 1:
        raise ValueError("Generated shops.json mixes multiple data versions.")
    data_version = next(iter(data_versions), None)
    source_counts: dict[str, int] = {}
    for shop in shops:
        source_type = str(shop.get("sourceType") or "UNKNOWN")
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
    import_manifest_path = data_directory / "import_manifest.json"
    if not import_manifest_path.is_file():
        return data_version, None, source_counts
    with import_manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    dataset_files = manifest.get("datasetFiles")
    if not isinstance(dataset_files, dict) or not dataset_files:
        raise ValueError("import_manifest.json is missing datasetFiles checksums.")
    actual_dataset_files: dict[str, dict[str, str]] = {}
    for filename, expected in dataset_files.items():
        path = data_directory / filename
        if not path.is_file():
            raise FileNotFoundError(f"Dataset file declared in import_manifest.json is missing: {filename}")
        digest = _sha256_file(path)
        if not isinstance(expected, dict) or expected.get("sha256") != digest:
            raise ValueError(f"Dataset file checksum does not match import_manifest.json: {filename}")
        actual_dataset_files[filename] = {"sha256": digest}
    dataset_sha256 = hashlib.sha256(
        json.dumps(actual_dataset_files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    if manifest.get("datasetSha256") != dataset_sha256:
        raise ValueError("import_manifest.json datasetSha256 is invalid.")
    shop_ids = sorted(shop["id"] for shop in shops)
    shop_ids_sha256 = hashlib.sha256(
        json.dumps(shop_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if manifest.get("shopIds") != shop_ids or manifest.get("shopIdsSha256") != shop_ids_sha256:
        raise ValueError("import_manifest.json does not match shops.json shop IDs.")
    if data_version and manifest.get("dataVersion") != data_version:
        raise ValueError("import_manifest.json does not match shops.json dataVersion.")
    manifest_source_counts = (manifest.get("provenance") or {}).get("sourceCounts")
    if manifest_source_counts is not None and manifest_source_counts != source_counts:
        raise ValueError("import_manifest.json provenance does not match shops.json source counts.")
    top_level_identity_mode = manifest.get("merchantIdentityMode")
    provenance_identity_mode = (manifest.get("provenance") or {}).get("merchantIdentityMode")
    if (
        top_level_identity_mode
        and provenance_identity_mode
        and top_level_identity_mode != provenance_identity_mode
    ):
        raise ValueError("import_manifest.json has conflicting merchant identity modes.")
    identity_mode = top_level_identity_mode or provenance_identity_mode
    if str(data_version or "").startswith("nyc-real-") and identity_mode != "REAL_ONLY":
        raise ValueError("nyc-real datasets must declare merchantIdentityMode as REAL_ONLY.")
    if identity_mode == "REAL_ONLY":
        image_path = data_directory / "shop_images.json"
        shop_images = None
        if image_path.is_file():
            with image_path.open(encoding="utf-8") as handle:
                shop_images = json.load(handle)
            if not isinstance(shop_images, list):
                raise ValueError("Generated shop_images.json must contain a list.")
        _validate_real_only_shops(shops, manifest, data_version, shop_images)
    return data_version, dataset_sha256, dict(sorted(source_counts.items()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_real_only_shops(
    shops: list[dict],
    manifest: dict,
    data_version: str | None,
    shop_images: list[dict] | None = None,
) -> None:
    if not shops:
        raise ValueError("REAL_ONLY dataset must contain at least one merchant.")
    allowed_sources = {"OPENSTREETMAP"}
    invalid_sources = [
        shop.get("id")
        for shop in shops
        if str(shop.get("sourceType") or "").upper() not in allowed_sources
    ]
    if invalid_sources:
        raise ValueError(
            "REAL_ONLY dataset contains non-real merchant sources for shop IDs: "
            + ", ".join(map(str, invalid_sources[:10]))
        )
    required_provenance = ("externalId", "sourceName", "sourceUrl", "sourceFetchedAt")
    missing_provenance = [
        shop.get("id")
        for shop in shops
        if any(not shop.get(field_name) for field_name in required_provenance)
    ]
    if missing_provenance:
        raise ValueError(
            "REAL_ONLY dataset is missing traceable merchant provenance for shop IDs: "
            + ", ".join(map(str, missing_provenance[:10]))
        )
    if not data_version or not data_version.startswith("nyc-real-"):
        raise ValueError("REAL_ONLY dataset must use a nyc-real-* data version.")
    if any(shop.get("dataVersion") != data_version for shop in shops):
        raise ValueError("Every REAL_ONLY merchant must declare the active data version.")
    source_keys = [(shop.get("sourceType"), shop.get("externalId")) for shop in shops]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("REAL_ONLY dataset contains duplicate source merchant identities.")
    missing_review_disclosures = [
        shop.get("id")
        for shop in shops
        if "reviews" not in set(shop.get("syntheticFields") or [])
    ]
    if missing_review_disclosures:
        raise ValueError(
            "REAL_ONLY merchants must disclose synthetic reviews for shop IDs: "
            + ", ".join(map(str, missing_review_disclosures[:10]))
        )
    if shop_images is None:
        # Backward-compatible safety gate for older bundles that predate the
        # per-image provenance file and therefore cannot prove an image is
        # merchant-specific.
        missing_image_disclosures = [
            shop.get("id")
            for shop in shops
            if "images" not in set(shop.get("syntheticFields") or [])
        ]
    else:
        shop_ids = {int(shop["id"]) for shop in shops}
        image_shop_ids = {
            int(image.get("shopId") or 0)
            for image in shop_images
            if int(image.get("shopId") or 0) in shop_ids
        }
        if image_shop_ids != shop_ids:
            missing = sorted(shop_ids - image_shop_ids)
            raise ValueError(
                "REAL_ONLY dataset is missing display images for shop IDs: "
                + ", ".join(map(str, missing[:10]))
            )
        illustrative_shop_ids = {
            int(image["shopId"])
            for image in shop_images
            if image.get("imageType") == "ILLUSTRATIVE"
            or image.get("matchType") == "CATEGORY_FALLBACK"
        }
        synthetic_fields_by_shop = {
            int(shop["id"]): set(shop.get("syntheticFields") or []) for shop in shops
        }
        missing_image_disclosures = [
            shop_id for shop_id in sorted(illustrative_shop_ids)
            if "images" not in synthetic_fields_by_shop[shop_id]
        ]
    if missing_image_disclosures:
        raise ValueError(
            "REAL_ONLY merchants with illustrative images must disclose synthetic images for shop IDs: "
            + ", ".join(map(str, missing_image_disclosures[:10]))
        )
    category_ids = {shop.get("typeId") for shop in shops}
    if category_ids != set(range(1, 7)):
        raise ValueError("REAL_ONLY dataset must cover all six NYC merchant categories.")
    provenance = manifest.get("provenance") or {}
    if provenance.get("mockShops") != 0:
        raise ValueError("REAL_ONLY manifest must declare mockShops as 0.")
    if provenance.get("realShops") != len(shops):
        raise ValueError("REAL_ONLY manifest realShops does not match shops.json.")
