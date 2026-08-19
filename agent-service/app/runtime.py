from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from app.actions.service import AgentActionService, HttpActionGateway, InMemoryActionGateway
from app.config import Settings
from app.domain.models import AgentMode
from app.graph.workflow import WorkflowServices, build_multi_agent_graph, build_single_agent_graph
from app.model_gateway import HeuristicModelGateway, OpenAICompatibleModelGateway
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    OpenAICompatibleEmbeddingService,
)
from app.rag.nyc_loader import load_generated_documents
from app.rag.qdrant_store import QdrantRagService
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
    qdrant_client: AsyncQdrantClient | None = None
    run_manager: AgentRunManager | None = None
    model_provider: str = "heuristic"
    action_service: AgentActionService | None = None
    rate_limiter: SlidingWindowRateLimiter | None = None
    metrics_token: str = ""

    @classmethod
    async def create(cls, settings: Settings) -> AgentRuntime:
        shops = _build_shop_service(settings)
        qdrant_client: AsyncQdrantClient | None = None
        indexed_documents = 0
        data_version: str | None = None
        dataset_sha256: str | None = None
        if settings.rag_data_directory is not None:
            data_version, dataset_sha256 = _validate_data_directory(
                settings.rag_data_directory.resolve()
            )

        if settings.rag_adapter == "qdrant":
            qdrant_client = _build_qdrant_client(settings.qdrant_location)
            rag = QdrantRagService(
                client=qdrant_client,
                embeddings=_build_embedding_service(settings),
                collection_name=settings.qdrant_collection,
            )
            if settings.rag_data_directory is not None:
                data_directory = settings.rag_data_directory.resolve()
                indexed_documents = await rag.index(
                    load_generated_documents(data_directory),
                    replace=True,
                )
        else:
            rag = InMemoryRagService()

        services = WorkflowServices(
            shops=shops,
            rag=rag,
            itinerary=HaversineItineraryService(),
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
            qdrant_client=qdrant_client,
            model_provider=settings.model_provider,
            action_service=AgentActionService(
                HttpActionGateway(
                    settings.backend_base_url,
                    timeout_seconds=settings.request_timeout_seconds,
                    fallback_authorization=settings.backend_auth_token,
                )
                if settings.adapter == "http"
                else InMemoryActionGateway()
            ),
            rate_limiter=SlidingWindowRateLimiter(settings.runs_per_minute),
            metrics_token=settings.metrics_token,
        )
        model_gateway = _build_model_gateway(settings)
        runtime.run_manager = AgentRunManager(
            runtime,
            SQLiteRunStore(settings.run_store_path),
            model_gateway,
            run_timeout_seconds=settings.run_timeout_seconds,
            max_recovery_attempts=settings.max_recovery_attempts,
        )
        await runtime.run_manager.recover()
        return runtime

    async def close(self) -> None:
        if self.run_manager is not None:
            await self.run_manager.close()
        if self.qdrant_client is not None:
            await self.qdrant_client.close()


def _build_shop_service(settings: Settings):
    if settings.adapter == "http":
        return HttpShopToolService(
            base_url=settings.backend_base_url,
            timeout_seconds=settings.request_timeout_seconds,
            auth_token=settings.backend_auth_token,
            max_candidates=settings.max_candidates,
        )
    if settings.rag_data_directory is not None:
        data_directory = settings.rag_data_directory.resolve()
        _validate_data_directory(data_directory)
        return GeneratedNycShopToolService(data_directory, settings.max_candidates)
    return MockShopToolService()


def _build_qdrant_client(location: str) -> AsyncQdrantClient:
    if location.startswith(("http://", "https://")):
        return AsyncQdrantClient(url=location)
    if location == ":memory:":
        return AsyncQdrantClient(location=location)
    return AsyncQdrantClient(path=location)


def _build_embedding_service(settings: Settings):
    if settings.embedding_provider == "openai":
        return OpenAICompatibleEmbeddingService(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    return DeterministicHashEmbeddingService(dimensions=settings.embedding_dimensions)


def _build_model_gateway(settings: Settings):
    heuristic = HeuristicModelGateway()
    if settings.model_provider == "heuristic":
        return heuristic
    return OpenAICompatibleModelGateway(
        provider=settings.model_provider,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        timeout_seconds=settings.model_timeout_seconds,
        fallback=heuristic if settings.model_fallback_to_heuristic else None,
    )


def _validate_data_directory(data_directory: Path) -> tuple[str | None, str | None]:
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
    import_manifest_path = data_directory / "import_manifest.json"
    if not import_manifest_path.is_file():
        return data_version, None
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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
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
    return data_version, dataset_sha256
