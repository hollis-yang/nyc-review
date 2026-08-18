from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.graph.workflow import WorkflowServices, build_multi_agent_graph
from app.rag.embeddings import (
    DeterministicHashEmbeddingService,
    OpenAICompatibleEmbeddingService,
)
from app.rag.nyc_loader import load_generated_documents
from app.rag.qdrant_store import QdrantRagService
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
    adapter_name: str
    rag_name: str
    indexed_documents: int = 0
    qdrant_client: AsyncQdrantClient | None = None

    @classmethod
    async def create(cls, settings: Settings) -> AgentRuntime:
        shops = _build_shop_service(settings)
        qdrant_client: AsyncQdrantClient | None = None
        indexed_documents = 0

        if settings.rag_adapter == "qdrant":
            qdrant_client = _build_qdrant_client(settings.qdrant_location)
            rag = QdrantRagService(
                client=qdrant_client,
                embeddings=_build_embedding_service(settings),
                collection_name=settings.qdrant_collection,
            )
            if settings.rag_data_directory is not None:
                data_directory = settings.rag_data_directory.resolve()
                _validate_data_directory(data_directory)
                indexed_documents = await rag.index(load_generated_documents(data_directory))
        else:
            rag = InMemoryRagService()

        workflow = build_multi_agent_graph(
            WorkflowServices(
                shops=shops,
                rag=rag,
                itinerary=HaversineItineraryService(),
            )
        )
        return cls(
            workflow=workflow,
            adapter_name=settings.adapter,
            rag_name=settings.rag_adapter,
            indexed_documents=indexed_documents,
            qdrant_client=qdrant_client,
        )

    async def close(self) -> None:
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


def _validate_data_directory(data_directory: Path) -> None:
    required = ["shops.json", "shop_reviews.json", "blogs.json", "blog_comments.json"]
    missing = [name for name in required if not (data_directory / name).is_file()]
    if missing:
        raise FileNotFoundError(f"RAG data directory {data_directory} is missing: {', '.join(missing)}")
